import asyncio
import json
import random
import re
from configparser import ConfigParser
from datetime import datetime, timedelta
from typing import NamedTuple, Dict, Optional, List
from urllib.parse import urlencode

import aiohttp
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
    def get_rate_limits(self, action: str) -> Dict[int, datetime]:
        return {}

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

    def record_action(self, action: str, user_id: int) -> None:
        rate_limits = self.get_rate_limits(action)
        rate_limits[user_id] = datetime.now()

    def is_rate_limited(self, action: str, user_id: int) -> bool:
        rate_limits = self.get_rate_limits(action)
        if not user_id in rate_limits:
            return False

        duration = timedelta(seconds=self.config['ratelimits'].getint(action))
        return rate_limits[user_id] + duration > datetime.now()

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

    async def http_get_request(self, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.text()

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

    async def get_quote_rank(self, quote_id: int) -> int:
        result = await self.qdb_query_single("""
            SELECT COUNT(DISTINCT(score)) + 1 AS rank
            FROM qdb_quotes
            WHERE score > (SELECT score FROM qdb_quotes WHERE id = %s)
        """, quote_id)

        return int(result['rank'])

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

    async def modify_quote_score(self, quote_id: int, amount: int):
        qdb_pool = await self.qdb_connection_pool()
        async with qdb_pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("UPDATE qdb_quotes SET score = score + %s WHERE id = %s", (amount, quote_id))
                await connection.commit()

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

        if message.content.startswith('!+q '):
            if self.is_rate_limited('quote.vote', message.author.id):
                return

            trigger, _, search_term = message.content.partition(' ')
            if not search_term.isdigit():
                return

            quote_id = int(search_term)
            quote = await self.get_quote(quote_id)
            if not quote:
                return await message.channel.send(f'Quote with id {search_term} does not exist')

            self.record_action('quote.vote', message.author.id)
            return await asyncio.gather(
                self.modify_quote_score(quote.id, +1),
                message.channel.send(f'Popularity of quote {quote.id} has increased.'),
            )

        if message.content.startswith('!-q '):
            if self.is_rate_limited('quote.vote', message.author.id):
                return

            trigger, _, search_term = message.content.partition(' ')
            if not search_term.isdigit():
                return

            quote_id = int(search_term)
            quote = await self.get_quote(quote_id)
            if not quote:
                return await message.channel.send(f'Quote with id {search_term} does not exist')

            self.record_action('quote.vote', message.author.id)
            return await asyncio.gather(
                self.modify_quote_score(quote.id, -1),
                message.channel.send(f'Popularity of quote {quote.id} has decreased.'),
            )

        if message.content.startswith('!iq '):
            trigger, _, search_term = message.content.partition(' ')
            if not search_term.isdigit():
                return

            quote_id = int(search_term)
            quote, rank = await asyncio.gather(
                self.get_quote(quote_id),
                self.get_quote_rank(quote_id),
            )

            if not quote:
                return await message.channel.send(f'Quote with id {search_term} does not exist')

            quote_info = f'Quote **{quote.id}** was added'
            if quote.creator:
                quote_info += f' by {quote.creator}'
            if quote.addchannel:
                quote_info += f' in channel {quote.addchannel}'
            if quote.adddate:
                quote_info += f' on {quote.adddate}'

            return await message.channel.send(f'{quote_info}. It is ranked {ordinal(rank)}.')

        # Google search
        if message.content.startswith('!g '):
            trigger, _, search_term = message.content.partition(' ')
            if not search_term:
                return

            results = await self.http_get_request('https://www.googleapis.com/customsearch/v1?' + urlencode({
                'q': search_term,
                'key': self.config['search.google']['api_key'],
                'cx': self.config['search.google']['search_engine_id'],
                'num': '1',
            }))

            json_results = json.loads(results)
            search_result, *rest = json_results['items']
            return await message.channel.send(
                f'**{search_result["title"]}**\n'
                f'<{search_result["link"]}>'
                f'\n'
                f'{search_result["snippet"]}\n',
            )

        # Hello world!
        if message.content == '!hello':
            await message.channel.send(f'Hello {message.author.mention}')
