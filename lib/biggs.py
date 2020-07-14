#!/usr/bin/env python

import logging
import json

# External dependencies
import discord
from tinydb import TinyDB, Query

# Logging
log = logging.getLogger("Biggs")
logging.addLevelName(15, "MESSAGE")
def msg(self, message, *args, **kws): self._log(15, message, args, **kws)
logging.Logger.msg = msg

def check_prefix(command_prefix: str, message: discord.Message):
  return message.content.startswith(command_prefix)

def remove_prefix(command_prefix: str, message: discord.Message):
  return message.content.replace(command_prefix, '')

class Biggs(discord.Client):
  def setup(self, config: dict):
    self._tinydb_instance   = TinyDB(f"{config['tinydb_path']}db.json")
    self._server_id         = config["server_id"] # type: int
    self._notice_channel_id = config["notice_channel_id"] # type: int

    self.run(config["token"])

  def db_insert(self, message_contents: str):
    parsed_json = json.loads(message_contents)
    self._tinydb_instance.insert(parsed_json)

  async def on_ready(self):
    log.info(f"Logged on as {self.user}!")

  async def on_message(self, message: discord.Message):
    log.msg(f"{message.channel}§{message.author}: {message.content}")
    try:
      log.info(f"Message from {message.author}: {message.content}")
      if check_prefix("$inserttest", message):
        self.db_insert(remove_prefix("$inserttest", message))

    except Exception as exc:
      log.error(exc)
      raise exc
