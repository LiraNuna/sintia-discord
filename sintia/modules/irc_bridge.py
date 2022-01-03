from __future__ import annotations

import re
from configparser import SectionProxy

import discord
import pydle


class IrcBridge(pydle.Client):
    config: SectionProxy
    forwarder: discord.Client
    discord_guild: discord.Guild
    discord_channel: discord.TextChannel

    user_regex: re.Pattern
    user_cache: dict[str, discord.Member]
    emoji_regex: re.Pattern
    emoji_cache: dict[str, discord.Emoji]

    def __init__(self, forwarder: discord.Client, config_section: str) -> None:
        pass

    async def on_connect(self):
        await self.join(self.config['irc_channel'])

    async def on_message(self, target: str, source: str, message: str) -> None:
        pass

    async def on_discord_message(self, client: discord.Client, message: discord.Message) -> None:
        pass

    async def reply(self, channel: discord.TextChannel, s: str) -> None:
        pass

    async def on_ctcp_action(self, source: str, target: str, message: str) -> None:
        pass
