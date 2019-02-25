import asyncio
from configparser import ConfigParser
from datetime import datetime
from typing import NamedTuple, Dict, Optional

import aiomysql
import discord

from sintia.util import memoize


class Quote(NamedTuple):
    id: int
    creator: str
    quote: str
    score: int
    adddate: datetime
    addchannel: str


class Sintia(discord.Client):
    config: ConfigParser

    def __init__(self, config: ConfigParser) -> None:
        super().__init__()

        self.config = config

    def run(self):
        super().run(self.config['discord']['token'])

    @memoize
    async def qdb_connection_pool(self):
        return await aiomysql.create_pool(
            host=self.config['quotes']['hostname'],
            port=self.config['quotes'].getint('post', 3306),
            user=self.config['quotes']['username'],
            password=self.config['quotes']['password'],
            db=self.config['quotes']['database'],
        )

    async def qdb_query(self, query: str, *args) -> Optional[Dict]:
        qdb_pool = await self.qdb_connection_pool()
        async with qdb_pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchone()

    async def get_latest_quote(self) -> Quote:
        quote = await self.qdb_query("SELECT * FROM qdb_quotes ORDER BY id DESC LIMIT 1")
        return Quote(**quote)

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        if message.content == '!lq':
            quote = await self.get_latest_quote()
            return await message.channel.send(
                f'Latest quote (**{quote.id}**, rated {quote.score}):\n'
                f'`{quote.quote}`',
            )

        # Hello world!
        if message.content == '!hello':
            await message.channel.send(f'Hello {message.author.mention}')
