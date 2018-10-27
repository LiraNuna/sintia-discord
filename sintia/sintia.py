import asyncio
import re
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

    def multiline_quote(self) -> str:
        nick_regex = '[a-zA-Z0-9`_\-|@+^[\]]*'

        quote = self.quote
        quote = re.sub(rf'(<{nick_regex}>)', r'\n\1', quote)
        quote = re.sub(rf'(\* {nick_regex} )', r'\n\1', quote)
        return quote


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

    async def get_quote(self, id: int) -> Optional[Quote]:
        quote = await self.qdb_query("SELECT * FROM qdb_quotes WHERE id = %s", id)
        if not quote:
            return None

        return Quote(**quote)

    async def get_random_quote(self) -> Quote:
        quote = await self.qdb_query("SELECT * FROM qdb_quotes ORDER BY RAND() LIMIT 1")
        return Quote(**quote)

    async def get_latest_quote(self) -> Quote:
        quote = await self.qdb_query("SELECT * FROM qdb_quotes ORDER BY id DESC LIMIT 1")
        return Quote(**quote)

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        # Get a random quote
        if message.content == '!q':
            quote, latest_quote = await asyncio.gather(
                self.get_random_quote(),
                self.get_latest_quote(),
            )

            return await message.channel.send(
                f'Quote **{quote.id}** of {latest_quote.id} (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # Get quote with id or search
        if message.content.startswith('!q '):
            trigger, _, search_term = message.content.partition(' ')
            if search_term.isdigit():
                quote, latest_quote = await asyncio.gather(
                    self.get_quote(int(search_term)),
                    self.get_latest_quote(),
                )

                if not quote:
                    await message.channel.send(f'Quote with id {search_term} does not exist')

                return await message.channel.send(
                    f'Quote **{quote.id}** of {latest_quote.id} (rated {quote.score}):\n'
                    f'```{quote.multiline_quote()}```',
                )

        if message.content == '!lq':
            quote = await self.get_latest_quote()
            return await message.channel.send(
                f'Latest quote (**{quote.id}**, rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # Hello world!
        if message.content == '!hello':
            await message.channel.send(f'Hello {message.author.mention}')
