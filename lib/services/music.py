import wavelink
import re
import subprocess
import yaml
import os
from typing import Union, List
from uuid import uuid4
from itertools import islice
from asyncio import Event, Queue, sleep
from math import ceil
from shlex import split
from collections import deque

# import datetime
# import humanize

import discord
from discord.utils import escape_markdown
from discord.ext import commands

from lib.utils.etc import Service, time_hms
from lib.utils.checks import in_dms
from lib.utils.text import fmt_list, fmt_plur

LAVALINK_READY = re.compile(" lavalink.server.Launcher\s+: Started Launcher")
RURL = re.compile("https?:\/\/.+") # barebones but good enough

def fmt_tracklist(tracks: List[wavelink.Track], page = 1) -> str:
  lst = []
  for i, track in enumerate(tracks):
    _out = ""
    _out += f"`{str(i + ((page - 1) * 10) + 1).rjust(2)}`"
    if track.is_stream:
      _out += f" - `[STREAM]`"
    else:
      _out += f" - `[{time_hms(track.length/1000)}]`"
    _out += f" {escape_markdown(track.title)}"
    lst.append(_out)
  return fmt_list(lst)

class MusicController:
  def __init__(self, bot, guild_id):
    self.bot = bot
    self.guild_id = guild_id
    self.channel = None

    self.next = Event()
    self.queue = Queue()

    self.volume = 40

    self.bot.loop.create_task(self.controller_loop())

  async def controller_loop(self):
    await self.bot.wait_until_ready()

    player = self.bot._wavelink.get_player(self.guild_id)
    await player.set_volume(self.volume)

    while True:
      self.next.clear()

      track = await self.queue.get() # type: wavelink.player.Track
      await player.play(track)

      _out = ""
      _out += f":arrow_forward: "
      if not track.is_stream:
        _out += f"`[{time_hms(track.length / 1000)}]`"
      else:
        _out += f"`[STREAM]`"
      _out += f" {escape_markdown(track.title)}"
      await self.channel.send(_out)

      await self.next.wait()

class Music(Service):
  def __init__(self, bot):
    super().__init__(bot)
    self.controllers = {}
    self.bot._wavelink = wavelink.Client(bot=self.bot)
    _path = self.bot._config["lavalink_path"]
    _args = self.bot._config["lavalink_args"]
    self._lavalink = subprocess.Popen(
      split(f"java -jar ./Lavalink.jar {_args}"),
      shell=False, cwd=_path,
      stdout=subprocess.PIPE,
      universal_newlines=True)
    self._searchresults = {}

    self.bot.add_listener(self.listen_searchresults, "on_message")

    rc = 0
    while True:
      stdout = self._lavalink.stdout.readline()
      if stdout == "" and rc is not None:
        break
      if LAVALINK_READY.search(stdout):
        self.bot.loop.create_task(self.start_nodes())
        break
      rc = self._lavalink.poll()

  # Guilds only
  async def cog_check(self, ctx: commands.Context):
    return not in_dms(ctx)

  # Close Lavalink when unloading
  def cog_unload(self):
    self._lavalink.terminate()

  async def start_nodes(self):
    await self.bot.wait_until_ready()

    _id = uuid4()

    if not os.path.exists("./lavalink/application.yml"):
      self.log.error("./lavalink/application.yml missing, exiting.")
      exit()
    with open("./lavalink/application.yml", "r") as y:
      config = yaml.load(y, Loader=yaml.FullLoader) # type: dict
    node = await self.bot._wavelink.initiate_node(
      identifier = str(_id),
      region     = "eu_west",
      host       = config["server"]["address"],
      port       = config["server"]["port"],
      rest_uri   = f"http://{config['server']['address']}:{config['server']['port']}",
      password   = config["lavalink"]["server"]["password"]
    )
    self.log.info(f"Initiated Wavelink node with identifier {_id}.")

    # Set our node hook callback
    node.set_hook(self.on_event_hook)

  async def on_event_hook(self, event):
    if isinstance(event, (wavelink.TrackEnd, wavelink.TrackException)):
      controller = self.get_controller(event.player)
      controller.next.set()

  def get_controller(self, value: Union[commands.Context, wavelink.Player]):
    if isinstance(value, commands.Context): gid = value.guild.id
    else:                                   gid = value.guild_id

    try:
      controller = self.controllers[gid]
    except KeyError:
      controller = MusicController(self.bot, gid)
      self.controllers[gid] = controller

    return controller

  @commands.command(name="join", aliases=["connect"])
  async def join_voice(self, ctx: commands.Context):
    """ Make me join your voice channel. """
    try:
      channel = ctx.author.voice.channel
    except AttributeError:
      await ctx.send("Please join a channel first...", delete_after=10)
      raise discord.DiscordException()
      #FIXME probably use a diff exception here instead

    player = self.bot._wavelink.get_player(ctx.guild.id)
    await ctx.send(f"Joining __{channel.mention}__.", delete_after=10)
    await player.connect(channel.id)

    controller = self.get_controller(ctx)
    controller.channel = ctx.channel

  @commands.command(aliases=["p"])
  async def play(self, ctx: commands.Context, *, query: str):
    """ Play something. """

    player = self.bot._wavelink.get_player(ctx.guild.id)
    if not player.is_connected:
      try: await ctx.invoke(self.join_voice)
      except discord.DiscordException: return

    if RURL.match(query):
      tracks = await self.bot._wavelink.get_tracks(f"{query}")
      if isinstance(tracks, wavelink.TrackPlaylist):
        for t in tracks.tracks: await self.queue_track(ctx, t, nomessage=True)
        await ctx.send(f"Added `{len(tracks.tracks)}` tracks to the queue.")
      else:
        await self.queue_track(ctx, tracks[0])
    elif ctx.author.id in self._searchresults.keys() and re.match(r"^(10|[1-9])$", query):
      await self.check_searchresults(ctx.message)
    else:
      if not (tracks := (await self.bot._wavelink.get_tracks(f"ytsearch:{query}"))[:10]):
        await ctx.send("Couldn't find anything.", delete_after=10)
      else:
        list_msg = await ctx.send(
          f"Results for \"{query}\":\n{fmt_tracklist(tracks)}"
        )

        if ctx.author.id in self._searchresults.keys():
          await self._searchresults[ctx.author.id]["list_msg"].delete()

        self._searchresults[ctx.author.id] = {
          "tracks": tracks,
          "list_msg": list_msg
        }

  async def queue_track(self, ctx: commands.Context, track: wavelink.player.Track, *, nomessage = False):
    controller = self.get_controller(ctx)
    controller.queue.put_nowait(track)
    if not nomessage:
      await ctx.send(f"Added to the queue: {escape_markdown(track.title)}")

  async def listen_searchresults(self, message: discord.Message):
    await self.check_searchresults(message)

  async def check_searchresults(self, message: discord.Message):
    if not (mid := message.author.id) in self._searchresults.keys(): return
    if self._searchresults[mid]["list_msg"].channel != message.channel: return
    if not (match := re.match(
      fr"^({re.escape(self.bot.command_prefix)}(p(lay)?\s+)?)?(10|[1-9])$",
      message.content)): return
    track = self._searchresults[mid]["tracks"][int(match[4]) - 1]
    await self._searchresults[mid]["list_msg"].delete()
    del self._searchresults[mid]
    await self.queue_track(await self.bot.get_context(message), track)

  @commands.command(aliases=["q", "list"])
  async def queue(self, ctx: commands.Context, *, pagenum: int = 1):
    """ List queued tracks. """
    if pagenum < 1: return

    player = self.bot._wavelink.get_player(ctx.guild.id) # type: wavelink.player.Player
    controller = self.get_controller(ctx)

    if not player.current and not controller.queue._queue:
      return await ctx.send("There's nothing in the queue...", delete_after=10)

    if (_c := player.current) is not None:
      _p = player.position
      time_remaining = time_hms(((_c.duration - _p) +
        sum(map(lambda t: t.duration,
          filter(lambda t: not t.is_stream, controller.queue._queue))
        )
      ) / 1000)
      _uri = _c.uri
      _title = _c.title
      _is_stream = _c.is_stream
      _length = _c.length
    else:
      # Something's gone wrong
      _p = 0
      _is_stream = False
      _title = "Something's gone horribly wrong!"
      _length = 0
      _uri = "https://html5zombo.com"
      time_remaining = "??:??"

    _out = ""
    _out += f":arrow_forward: "
    if not _is_stream:
      _out += f"`[{time_hms(_p / 1000)}/{time_hms(_length / 1000)}]`"
    else:
      _out += f"`[STREAM]`"
    _out += f" {escape_markdown(_title)}\n<{_uri}>\n"

    if controller.queue._queue:
      qsize = controller.queue.qsize()
      numpages = ceil(qsize / 10)

      if pagenum > numpages:
        return await ctx.send(f"There's only {numpages} page{fmt_plur(numpages)} of tracks in the queue.", delete_after=10)

      tracks = list(islice(controller.queue._queue, (pagenum - 1) * 10, (pagenum - 1) * 10 + 10))
      if numpages > 1:
        _out += f"Page `{pagenum}/{numpages}` "
      _out += f"(`{qsize}` item{fmt_plur(qsize)}, `[{time_remaining}]` remaining)\n"
      _out += fmt_tracklist(tracks, page=pagenum)
    else:
      _out += "Nothing queued."
    await ctx.send(_out)

  @commands.command(aliases=["np", "what"])
  async def nowplaying(self, ctx: commands.Context):
    """ Get info for the current track. """
    player = self.bot._wavelink.get_player(ctx.guild.id)

    if not player.current:
      return await ctx.send("I'm not playing anything...", delete_after=10)

    _c = player.current # type: wavelink.Track
    _p = player.position

    await ctx.send(_c.info["uri"])
    _out = ""
    if not _c.is_stream:
      _out += f"`[{time_hms(_p / 1000)}/{time_hms(_c.length / 1000)}]`"
    else:
      _out += "`[STREAM]`"
    _out += f" {escape_markdown(_c.title)}\n"
    await ctx.send(_out)

  @commands.command(aliases=["s", "next"])
  async def skip(self, ctx: commands.Context, *, which: str = ""):
    """ Skip track(s). """
    player = self.bot._wavelink.get_player(ctx.guild.id)

    if which == "":
      if not player.is_playing:
        return await ctx.send("I'm not playing anything...", delete_after=10)
      await ctx.send(f"Skipping {escape_markdown(player.current.title)}", delete_after=10)
      return await player.stop()
    elif match := re.match(r"^(\d+)(-(\d+))?$", which):
      a = int(match[1])
      if match[3]:
        b = int(match[3])
        if a == 0 or b == 0:
          return await ctx.send("No 0s please...", delete_after=10)
        if a > b:
          return await ctx.send(f"Numbers that make sense, please...", delete_after=10)
        if a == b:
          b = None
      else:
        b = None

      controller = self.get_controller(ctx)
      if b is not None:
        controller.queue._queue = deque(
          [i for _i, i in enumerate(controller.queue._queue) if _i + 1 not in range(a + 1, b + 1)])
        await ctx.send(f"Skipped tracks {a}-{b}.", delete_after=10)
      else:
        _t = escape_markdown(controller.queue._queue[a].title)
        controller.queue._queue = deque(
          [i for _i, i in enumerate(controller.queue._queue) if _i + 1 != a])
        await ctx.send(f"Skipped track {a}: {_t}", delete_after=10)

  @commands.command(aliases=["unresume"])
  async def pause(self, ctx: commands.Context):
    """ Pause the player. """
    player = self.bot._wavelink.get_player(ctx.guild.id) # type: wavelink.Player
    if not player.is_playing or player.is_paused:
      return await ctx.send("I'm not playing anything...", delete_after=10)

    await ctx.send("Pausing.", delete_after=10)
    await player.set_pause(True)

  @commands.command(aliases=["unpause", "continue"])
  async def resume(self, ctx: commands.Context):
    """ Resume the player from a paused state. """
    player = self.bot._wavelink.get_player(ctx.guild.id)
    if not player.is_paused:
      return await ctx.send("I'm not paused...", delete_after=10)

    await ctx.send("Resuming.", delete_after=10)
    await player.set_pause(False)

  @commands.command()
  async def volume(self, ctx: commands.Context, *, vol: int):
    """ Set the volume. """
    player = self.bot._wavelink.get_player(ctx.guild.id)
    controller = self.get_controller(ctx)

    vol = max(min(vol, 1000), 0)
    controller.volume = vol

    await ctx.send(f"Volume is now `{vol}%`.")
    await player.set_volume(vol)

  @commands.command(aliases=["disconnect", "dc", "leave", "stop", "kill", "die", "fuckoff"])
  async def destroy(self, ctx: commands.Context):
    """ Reset and disconnect. """
    player = self.bot._wavelink.get_player(ctx.guild.id)

    try: del self.controllers[ctx.guild.id]
    except KeyError: return await player.disconnect()

    await player.disconnect()
    await ctx.send("Ok, bye!", delete_after=10)

  # @commands.command()
  # async def info(self, ctx: commands.Context):
  #   """ Retrieve various Node/Server/Player information. """
  #   player = self.bot._wavelink.get_player(ctx.guild.id)
  #   node = player.node # type: wavelink.Node

  #   used  = humanize.naturalsize(node.stats.memory_used)
  #   total = humanize.naturalsize(node.stats.memory_allocated)
  #   free  = humanize.naturalsize(node.stats.memory_free)
  #   cpu   = node.stats.cpu_cores

  #   fmt = f"**WaveLink:** `{wavelink.__version__}`\n\n" \
  #     f"Connected to `{len(self.bot._wavelink.nodes)}` nodes.\n" \
  #     f"Best available Node `{self.bot._wavelink.get_best_node().__repr__()}`\n" \
  #     f"`{len(self.bot._wavelink.players)}` players are distributed on nodes.\n" \
  #     f"`{node.stats.players}` players are distributed on server.\n" \
  #     f"`{node.stats.playing_players}` players are playing on server.\n\n" \
  #     f"Server Memory: `{used}/{total}` | `({free} free)`\n" \
  #     f"Server CPU: `{cpu}`\n\n" \
  #     f"Server Uptime: `{datetime.timedelta(milliseconds=node.stats.uptime)}`"
  #   await ctx.send(fmt)
