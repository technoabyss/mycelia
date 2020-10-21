import json
import logging
import datetime
import schedule
from asyncio import create_task as await_this

import jsonschema
from tinydb import where
from discord.ext import commands, tasks

from lib.utils import is_mod, in_guild, react, md_list

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

class Schedule(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self._schedule = bot._db.table("schedule")
    self._schedule_task_schema = json.load(open("./lib/schema/schedule_task.json"))

    # Set up all saved tasks
    for task in self._schedule.all():
      self.setup_task(task)

    self.tick.start()

  # Guild-only
  async def cog_check(self, ctx: commands.Context):
    return in_guild(ctx)

  # Set up one task
  def setup_task(self, task):
    def task_message(self, channel, message):
      await_this(self.bot._guild.get_channel(channel).send(message))

    if task["type"] == "message":
      eval(task["directive"])(lambda: task_message(self, task["channel"], task["message"]))

  #Add to schedule
  def add_task(self, task: dict):
    """ Insert """
    # Validate task
    jsonschema.validate(instance=task, schema=self._schedule_task_schema)
    # Submit validated JSON
    self._schedule.insert(task)
    # Set up task immediately
    self.setup_task(task)

  # Commands
  @commands.group(aliases=["sch"])
  async def schedule(self, ctx: commands.Context):
    """ Restricted to moderators """
    if ctx.invoked_subcommand is None: await ctx.send_help("schedule")

  @schedule.command(aliases=["a"])
  @commands.check(is_mod)
  async def add(self, ctx: commands.Context, *, data: str):
    """ Adds a task to the schedule """
    try:
      # Parse and add task
      data = json.loads(data)
      self.add_task(data)

      await react(ctx, "confirm")
      await ctx.send(f"Added task of type `{data['type']}` to the schedule.", delete_after=10)

    except (jsonschema.exceptions.ValidationError, json.decoder.JSONDecodeError) as exc:
      await react(ctx, "deny")
      if exc.__class__ == json.decoder.JSONDecodeError: msg = exc
      else:                                             msg = exc.message
      await ctx.send(f"JSON Error: {msg}")

  @schedule.command(aliases=["l"])
  @commands.check(is_mod)
  async def list(self, ctx: commands.Context):
    """ List existing tasks """
    await ctx.send(md_list(self._schedule.all()))

  @tasks.loop(seconds=1)
  async def tick(self):
    schedule.run_pending()
    print("Tick")

  @tick.before_loop
  async def before_tick(self):
    # Wait for on_ready before beginning
    await self.bot.wait_until_ready()

  def cog_unload(self):
    # Cancel task when unloading the cog
    self.tick.cancel()