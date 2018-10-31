import asyncio
import random
import re
from configparser import ConfigParser
from datetime import datetime
from typing import NamedTuple, Dict, Optional, List

import aiomysql
import discord

from sintia.util import memoize
from sintia.util import ordinal


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
        qdb_config = self.config['quotes']
        return await aiomysql.create_pool(
            host=qdb_config['hostname'],
            port=qdb_config.getint('post', 3306),
            user=qdb_config['username'],
            password=qdb_config['password'],
            db=qdb_config['database'],
        )

    async def qdb_query_single(self, query: str, *args) -> Optional[Dict]:
        qdb_pool = await self.qdb_connection_pool()
        async with qdb_pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchone()

    async def qdb_query_all(self, query: str, *args) -> Optional[List[Dict]]:
        qdb_pool = await self.qdb_connection_pool()
        async with qdb_pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchall()

    async def get_quote(self, id: int) -> Optional[Quote]:
        quote = await self.qdb_query_single("SELECT * FROM qdb_quotes WHERE id = %s", id)
        if not quote:
            return None

        return Quote(**quote)

    async def get_random_quote(self) -> Quote:
        quote = await self.qdb_query_single("SELECT * FROM qdb_quotes ORDER BY RAND() LIMIT 1")
        return Quote(**quote)

    async def get_latest_quote(self) -> Quote:
        quote = await self.qdb_query_single("SELECT * FROM qdb_quotes ORDER BY id DESC LIMIT 1")
        return Quote(**quote)

    async def get_best_quote(self) -> Quote:
        quote = await self.qdb_query_single("SELECT * FROM qdb_quotes ORDER BY score DESC LIMIT 1")
        return Quote(**quote)

    async def get_quotes_for_rank(self, rank: int) -> List[Quote]:
        quotes = await self.qdb_query_all("""
            SELECT * FROM qdb_quotes WHERE score = (
                SELECT score FROM qdb_quotes GROUP BY score ORDER BY score DESC LIMIT %s,1
            ) ORDER BY id ASC
        """, rank)

        return [Quote(**quote) for quote in quotes]

    async def find_quotes_by_search_term(self, search_term: str) -> List[Quote]:
        quotes = await self.qdb_query_all(
            "SELECT * FROM qdb_quotes WHERE quote LIKE %s ORDER BY id ASC",
            f'%{search_term}%',
        )

        return [Quote(**quote) for quote in quotes]

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

        if message.content == '!bq':
            quote = await self.get_best_quote()
            return await message.channel.send(
                f'The most popular quote is Quote **{quote.id}** (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        if message.content.startswith('!bq '):
            trigger, _, search_term = message.content.partition(' ')
            if search_term.isdigit():
                rank = int(search_term)
                if rank <= 0:
                    return

                quotes = await self.get_quotes_for_rank(rank)
                if len(quotes) == 1:
                    quote = quotes[0]
                    return await message.channel.send(
                        f'The {ordinal(rank)} most popular quote is Quote **{quote.id}** (rated {quote.score}):\n'
                        f'```{quote.multiline_quote()}```',
                    )

                await message.channel.send(f'Quotes sharing the {ordinal(rank)} rank (ranked {quotes[0].score}):')
                for quote in quotes:
                    await message.channel.send(f'Quote **{quote.id}**:\n```{quote.multiline_quote()}```')

        if message.content.startswith('!fq '):
            trigger, _, search_term = message.content.partition(' ')

            quotes = await self.find_quotes_by_search_term(search_term)
            if not quotes:
                return await message.channel.send('No quotes match that search term.')

            total_results = len(quotes)
            random_quote_index = random.choice(range(total_results))

            quote = quotes[random_quote_index]
            return await message.channel.send(
                f'Result {random_quote_index + 1} of {total_results}: Quote **{quote.id}** (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # Hello world!
        if message.content == '!hello':
            await message.channel.send(f'Hello {message.author.mention}')
