import re
import asyncio
from typing import Dict
from configparser import SectionProxy

import discord
import pydle

from sintia.config import get_config_section


class IrcBridge(pydle.Client):
    config: SectionProxy
    forwarder: discord.Client
    discord_guild: discord.Guild
    discord_channel: discord.TextChannel

    user_regex: re.Pattern
    user_cache: Dict[str, discord.Member]
    emoji_regex: re.Pattern
    emoji_cache: Dict[str, discord.Emoji]

    def __init__(self, forwarder: discord.Client, config_section: str) -> None:
        self.config = get_config_section(config_section)

        super().__init__ (forwarder.user.name, realname=forwarder.user.name)

        self.forwarder = forwarder
        self.discord_guild = forwarder.get_guild(self.config.getint('discord_guild'))
        self.discord_channel = self.discord_guild.get_channel(self.config.getint('discord_channel'))

        forwarder.loop.create_task(self.connect(
            hostname=self.config['irc_host'],
            port=self.config['irc_port'],
        ))

        forwarder.add_message_listener(self.on_discord_message)

        # Build ping-back cache
        self.user_cache = {
            member.name.lower(): member
            for member in self.discord_guild.members
        }
        self.user_cache.update({
            member.nick.lower(): member
            for member in self.discord_guild.members
            if member.nick is not None
        })

        # Nick matcher
        self.user_regex = re.compile(
            rf'@?\b({"|".join(map(re.escape, self.user_cache.keys()))})\b',
            re.IGNORECASE,
        )

        # Emoji cache
        self.emoji_cache = {
            emoji.name: emoji
            for emoji in self.discord_guild.emojis
        }
        self.emoji_regex = re.compile(rf':({"|".join(map(re.escape, self.emoji_cache.keys()))}):')

    async def on_connect(self):
        await self.join(self.config['irc_channel'])

    async def on_message(self, target: str, source: str, message: str) -> None:
        if source == self.nickname:
            return
        if target != self.config['irc_channel']:
            return

        # Mentions
        message = self.user_regex.sub(
            lambda match: self.user_cache[match[1].lower()].mention,
            message,
        )
        # Emojis
        message = self.emoji_regex.sub(
            lambda match: str(self.emoji_cache[match[1]]),
            message,
        )

        await self.discord_channel.send(f'<**{source}**> {message}')

    async def on_discord_message(self, client: discord.Client, message: discord.Message) -> None:
        if not self.connected:
            return
        if message.author == self.forwarder.user:
            return
        if message.channel != self.discord_channel:
            return

        full_message = message.clean_content + ' ' + '\n'.join(attachment.url for attachment in message.attachments)
        await self.message(self.config['irc_channel'], '\n'.join(
            f'<\x02{message.author.display_name}\x02> {line}'
            for line in full_message.split('\n')
        ))

    async def on_ctcp_action(self, source: str, target: str, message: str) -> None:
        if source == self.nickname:
            return
        if target != self.config['irc_channel']:
            return

        await self.discord_channel.send(f'* **{source}** {message}')
