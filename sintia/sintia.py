import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import Dict, Callable, Any
from urllib.parse import urlencode

import aiohttp
import discord

from sintia.config import get_config_section
from sintia.modules import quotes
from sintia.util import memoize
from sintia.util import ordinal


class CommandProcessor:
    prefix: str
    commands: Dict[str, Callable]

    def __init__(self, *, prefix: str) -> None:
        self.prefix = prefix
        self.commands = {}

    def __call__(self, command: str):
        def decorator(func: Callable) -> Callable:
            self.commands[self.prefix + command] = func

            return func

        return decorator

    async def process_message(self, instance: Any, message: discord.Message) -> None:
        trigger, _, argument = message.clean_content.partition(' ')
        if trigger not in self.commands:
            return

        trigger_handler = self.commands[trigger]
        return await trigger_handler(instance, message, argument.strip())


class Sintia(discord.Client):
    command_handler: CommandProcessor = CommandProcessor(prefix='!')

    def run(self):
        discord_config = get_config_section('discord')

        super().run(discord_config['token'])

    @memoize
    def get_rate_limits(self, action: str) -> Dict[int, datetime]:
        return {}

    def record_action(self, action: str, user_id: int) -> None:
        rate_limits = self.get_rate_limits(action)
        rate_limits[user_id] = datetime.now()

    def is_rate_limited(self, action: str, user_id: int) -> bool:
        rate_limits = self.get_rate_limits(action)
        if not user_id in rate_limits:
            return False

        rate_limit_config = get_config_section('ratelimits')
        duration = timedelta(seconds=rate_limit_config.getint(action))
        return rate_limits[user_id] + duration > datetime.now()

    async def http_get_request(self, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.text()

    @command_handler('q')
    async def read_quote(self, message: discord.Message, argument: str) -> None:
        # When no argument is given, we display a random quote
        if not argument:
            quote, latest_quote = await asyncio.gather(
                quotes.get_random_quote(),
                quotes.get_latest_quote(),
            )

            return await message.channel.send(
                f'Quote **{quote.id}** of {latest_quote.id} (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # Otherwise, we attempt to either show a quote with id if it's an integer
        if argument.isdigit():
            quote, latest_quote = await asyncio.gather(
                quotes.get_quote(int(argument)),
                quotes.get_latest_quote(),
            )

            if not quote:
                await message.channel.send(f'Quote with id {argument} does not exist')

            return await message.channel.send(
                f'Quote **{quote.id}** of {latest_quote.id} (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # If it's not a digit, it's treated as a search term
        return await self.find_quote(message, argument)

    @command_handler('fq')
    async def find_quote(self, message: discord.Message, argument: str) -> None:
        search_results = await quotes.find_quotes_by_search_term(argument)
        if not search_results:
            return await message.channel.send('No quotes match that search term.')

        total_results = len(search_results)
        random_quote_index = random.choice(range(total_results))

        quote = search_results[random_quote_index]
        return await message.channel.send(
            f'Result {random_quote_index + 1} of {total_results}: Quote **{quote.id}** (rated {quote.score}):\n'
            f'```{quote.multiline_quote()}```',
        )

    @command_handler('lq')
    async def last_quote(self, message: discord.Message, argument: str) -> None:
        quote = await quotes.get_latest_quote()
        return await message.channel.send(
            f'Latest quote (**{quote.id}**, rated {quote.score}):\n'
            f'```{quote.multiline_quote()}```',
        )

    @command_handler('bq')
    async def best_quote(self, message: discord.Message, argument: str) -> None:
        # No param simply shows the best quote
        if not argument:
            quote = await quotes.get_best_quote()
            return await message.channel.send(
                f'The most popular quote is Quote **{quote.id}** (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        # Only digit arguments are understood as rank
        if not argument.isdigit():
            return

        rank = int(argument)
        if rank <= 0:
            return

        quotes_for_rank = await quotes.get_quotes_for_rank(rank)
        if len(quotes_for_rank) == 1:
            quote = quotes_for_rank[0]
            return await message.channel.send(
                f'The {ordinal(rank)} most popular quote is Quote **{quote.id}** (rated {quote.score}):\n'
                f'```{quote.multiline_quote()}```',
            )

        await message.channel.send(f'Quotes sharing the {ordinal(rank)} rank (ranked {quotes_for_rank[0].score}):')
        for quote in quotes_for_rank:
            await message.channel.send(f'Quote **{quote.id}**:\n```{quote.multiline_quote()}```')

    @command_handler('iq')
    async def quote_info(self, message: discord.Message, argument: str) -> None:
        if not argument.isdigit():
            return

        quote_id = int(argument)
        quote, rank = await asyncio.gather(
            quotes.get_quote(quote_id),
            quotes.get_quote_rank(quote_id),
        )

        if not quote:
            return await message.channel.send(f'Quote with id {argument} does not exist')

        quote_info = f'Quote **{quote.id}** was added'
        if quote.creator:
            quote_info += f' by {quote.creator}'
        if quote.addchannel:
            quote_info += f' in channel {quote.addchannel}'
        if quote.adddate:
            quote_info += f' on {quote.adddate}'

        return await message.channel.send(f'{quote_info}. It is ranked {ordinal(rank)}.')

    @command_handler('+q')
    async def upvote_quote(self, message: discord.Message, argument: str) -> None:
        if self.is_rate_limited('quote.vote', message.author.id):
            return

        if not argument.isdigit():
            return

        quote_id = int(argument)
        quote = await quotes.get_quote(quote_id)
        if not quote:
            return await message.channel.send(f'Quote with id {argument} does not exist')

        self.record_action('quote.vote', message.author.id)
        return await asyncio.gather(
            quotes.modify_quote_score(quote.id, +1),
            message.channel.send(f'Popularity of quote {quote.id} has increased.'),
        )

    @command_handler('-q')
    async def downvote_quote(self, message: discord.Message, argument: str) -> None:
        if self.is_rate_limited('quote.vote', message.author.id):
            return

        if not argument.isdigit():
            return

        quote_id = int(argument)
        quote = await quotes.get_quote(quote_id)
        if not quote:
            return await message.channel.send(f'Quote with id {quote_id} does not exist')

        self.record_action('quote.vote', message.author.id)
        return await asyncio.gather(
            quotes.modify_quote_score(quote.id, -1),
            message.channel.send(f'Popularity of quote {quote.id} has decreased.'),
        )

    @command_handler('g')
    async def google_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        google_config = get_config_section('search.google')
        results = await self.http_get_request('https://www.googleapis.com/customsearch/v1?' + urlencode({
            'q': argument,
            'key': google_config['api_key'],
            'cx': google_config['search_engine_id'],
            'num': '1',
        }))

        json_results = json.loads(results)
        search_result, *rest = json_results.get('items', [None])
        if not search_result:
            return await message.channel.send(f'No results found for `{argument}`')

        return await message.channel.send(
            f'**{search_result["title"]}**\n'
            f'<{search_result["link"]}>'
            f'\n'
            f'{search_result["snippet"]}\n',
        )

    @command_handler('gi')
    async def google_image_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        google_config = get_config_section('search.google')
        results = await self.http_get_request('https://www.googleapis.com/customsearch/v1?' + urlencode({
            'q': argument,
            'searchType': 'image',
            'key': google_config['api_key'],
            'cx': google_config['search_engine_id'],
            'num': '1',
        }))

        json_results = json.loads(results)
        search_result, *rest = json_results.get('items', [None])
        if not search_result:
            return await message.channel.send(f'No results found for `{argument}`')

        return await message.channel.send(search_result["link"])

    @command_handler('hello')
    async def greet(self, message: discord.Message, argument: str) -> None:
        return await message.channel.send(f'Hello {message.author.mention}')

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        return await self.command_handler.process_message(self, message)
