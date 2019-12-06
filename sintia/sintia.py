import asyncio
import json
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Callable, Union, MutableMapping, Awaitable, Optional

import aiohttp
import discord

from sintia.config import get_config_section
from sintia.modules import quotes, user_votes
from sintia.modules import user_stats
from sintia.modules.quotes import Quote
from sintia.util import memoize
from sintia.util import ordinal
from sintia.util import plural
from sintia.util import readable_timedelta

Callback = Callable[[discord.Client, discord.Message, str], Awaitable[None]]


class CommandProcessor:
    prefix: str
    commands: Dict[str, Callback]

    def __init__(self, *, prefix: str) -> None:
        self.prefix = prefix
        self.commands = {}

    def __call__(self, command: str):
        def decorator(func: Callback) -> Callback:
            self.commands[self.prefix + command] = func

            return func

        return decorator

    async def process_message(self, instance: discord.Client, message: discord.Message) -> None:
        trigger, _, argument = message.clean_content.partition(' ')
        if trigger not in self.commands:
            return

        trigger_handler = self.commands[trigger]
        await asyncio.gather(
            trigger_handler(instance, message, argument.strip()),
            user_stats.record_command(message, trigger),
        )


class Sintia(discord.Client):
    command_handler: CommandProcessor = CommandProcessor(prefix='!')

    def __init__(self, *, loop=None, **options):
        discord_config = get_config_section('discord')

        options.setdefault('max_messages', discord_config.getint('max_messages'))

        super().__init__(
            loop=loop,
            **options,
        )

    def run(self):
        discord_config = get_config_section('discord')

        super().run(discord_config['token'])

    @memoize
    def get_rate_limits(self, action: str, *sections: Union[str, int]) -> Dict[int, datetime]:
        return {}

    def record_action(self, user_id: int, action: str, *sections: Union[str, int]) -> None:
        rate_limits = self.get_rate_limits(action, *sections)
        rate_limits[user_id] = datetime.now()

    def is_rate_limited(self, user_id: int, action: str, *sections: Union[str, int]) -> bool:
        rate_limits = self.get_rate_limits(action, *sections)
        if not user_id in rate_limits:
            return False

        rate_limit_config = get_config_section('ratelimits')
        duration = timedelta(seconds=rate_limit_config.getint(action))
        return rate_limits[user_id] + duration > datetime.now()

    async def http_get_request(self, url: str, *, params: Optional[Dict[str, str]] = None) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                return await response.text()

    def format_quote(self, quote: Quote) -> str:
        return (
            f'Quote **#{quote.id}** (rated {quote.score}):\n'
            f'```{quote.multiline_quote()}```'
        )

    @command_handler('q')
    async def read_quote(self, message: discord.Message, argument: str) -> None:
        # When no argument is given, we display a random quote
        if not argument:
            quote, latest_quote = await asyncio.gather(
                quotes.get_random_quote(),
                quotes.get_latest_quote(),
            )

            return await message.channel.send(self.format_quote(quote))

        # Otherwise, we attempt to either show a quote with id if it's an integer
        if argument.isdigit():
            quote, latest_quote = await asyncio.gather(
                quotes.get_quote(int(argument)),
                quotes.get_latest_quote(),
            )

            if not quote:
                await message.channel.send(f'Quote with id {argument} does not exist')

            return await message.channel.send(self.format_quote(quote))

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
            f'Result {random_quote_index + 1} of {total_results}: {self.format_quote(quote)}'
        )

    @command_handler('lq')
    async def last_quote(self, message: discord.Message, argument: str) -> None:
        quote = await quotes.get_latest_quote(containing=argument)
        if not quote:
            return await message.channel.send(f'No quotes found')

        extra_message = ''
        if argument:
            extra_message = 'containing search term '

        return await message.channel.send(f'Latest quote {extra_message}is {self.format_quote(quote)}')

    @command_handler('bq')
    async def best_quote(self, message: discord.Message, argument: str) -> None:
        # No param simply shows the best quote
        if not argument:
            quote = await quotes.get_best_quote()
            return await message.channel.send(f'The most popular quote is {self.format_quote(quote)}')

        # Only digit arguments are understood as rank
        if not argument.isdigit():
            return

        rank = int(argument)
        if rank <= 0:
            return

        quotes_for_rank = await quotes.get_quotes_for_rank(rank)
        if len(quotes_for_rank) == 1:
            quote = quotes_for_rank[0]
            return await message.channel.send(f'The {ordinal(rank)} most popular quote is {self.format_quote(quote)}')

        score = quotes_for_rank[0].score
        quotes_to_show = min(3, len(quotes_for_rank))
        await message.channel.send(f'{quotes_to_show} quotes sharing the {ordinal(rank)} rank ({score} votes):')
        for quote in quotes_for_rank[:quotes_to_show]:
            await message.channel.send(self.format_quote(quote))

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

        quote_info = f'Quote **#{quote.id}** was added'
        if quote.creator:
            quote_info += f' by {quote.creator}'
        if quote.addchannel:
            quote_info += f' in channel {quote.addchannel}'
        if quote.adddate:
            quote_info += f' on {quote.adddate}'

        return await message.channel.send(f'{quote_info}. It is ranked {ordinal(rank)}.')

    @command_handler('aq')
    async def add_quote(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        if self.is_rate_limited(message.author.id, 'quote.add'):
            return

        self.record_action(message.author.id, 'quote.add')
        quote_id = await quotes.add_quote(message.author.display_name, argument, message.channel.name)
        return await message.channel.send(f'Quote **#{quote_id}** has been added.')

    @command_handler('+q')
    async def upvote_quote(self, message: discord.Message, argument: str) -> None:
        if not argument.isdigit():
            return

        quote_id = int(argument)
        quote = await quotes.get_quote(quote_id)
        if not quote:
            return await message.channel.send(f'Quote with id {argument} does not exist')

        if self.is_rate_limited(message.author.id, 'quote.vote', quote_id):
            return

        self.record_action(message.author.id, 'quote.vote', quote_id)
        await quotes.modify_quote_score(quote.id, +1)
        return await message.channel.send(f'Popularity of quote {quote.id} has increased.')

    @command_handler('-q')
    async def downvote_quote(self, message: discord.Message, argument: str) -> None:
        if not argument.isdigit():
            return

        quote_id = int(argument)
        quote = await quotes.get_quote(quote_id)
        if not quote:
            return await message.channel.send(f'Quote with id {quote_id} does not exist')

        if self.is_rate_limited(message.author.id, 'quote.vote', quote_id):
            return

        self.record_action(message.author.id, 'quote.vote', quote_id)
        await quotes.modify_quote_score(quote.id, -1),
        return await message.channel.send(f'Popularity of quote {quote.id} has decreased.')

    @command_handler('g')
    async def google_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        google_config = get_config_section('search.google')
        results = await self.http_get_request('https://www.googleapis.com/customsearch/v1', params={
            'q': argument,
            'key': google_config['api_key'],
            'cx': google_config['search_engine_id'],
            'num': '1',
        })

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
        results = await self.http_get_request('https://www.googleapis.com/customsearch/v1', params={
            'q': argument,
            'searchType': 'image',
            'key': google_config['api_key'],
            'cx': google_config['search_engine_id'],
            'safe': 'off' if message.channel.is_nsfw() else 'active',
            'num': '1',
        })

        json_results = json.loads(results)
        search_result, *rest = json_results.get('items', [None])
        if not search_result:
            return await message.channel.send(f'No results found for `{argument}`')

        return await message.channel.send(search_result["link"])

    @command_handler('gif')
    async def google_gif_search(self, message: discord.Message, argument: str) -> None:
        return await self.google_image_search(message, argument + ' filetype:gif')

    @command_handler('yt')
    async def youtube_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        youtube_config = get_config_section('search.youtube')
        results = await self.http_get_request('https://www.googleapis.com/youtube/v3/search', params={
            'q': argument,
            'part': 'id',
            'type': 'video',
            'key': youtube_config['api_key'],
            'maxResults': '1',
        })

        json_results = json.loads(results)
        search_result, *rest = json_results.get('items', [None])
        if not search_result:
            return await message.channel.send(f'No results found for `{argument}`')

        return await message.channel.send(f'https://www.youtube.com/watch?v={search_result["id"]["videoId"]}')

    @command_handler('w')
    async def wikipedia_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        raw_search_results = await self.http_get_request('https://en.wikipedia.org/w/api.php', params={
            'action': 'query',
            'format': 'json',
            'prop': 'extracts|info|pageimages',
            'indexpageids': 1,
            'generator': 'search',
            'utf8': 1,
            'exlimit': 1,
            'explaintext': 1,
            'inprop': 'url',
            'gsrsearch': argument,
            'gsrlimit': 1,
            'pithumbsize': 1024,
        })

        search_results = json.loads(raw_search_results)
        if 'query' not in search_results:
            return await message.channel.send(f'No results found for `{argument}`')

        page_id, *rest = search_results['query']['pageids']
        page_info = search_results['query']['pages'][page_id]
        paragraphs = page_info['extract'].split('\n')

        embed = discord.Embed(
            title=page_info['title'],
            description=paragraphs[0],
            url=page_info['canonicalurl'],
        )

        if 'thumbnail' in page_info:
            embed.set_thumbnail(url=page_info['thumbnail'].get('source'))

        return await message.channel.send(embed=embed)

    @command_handler('ud')
    async def urbandictionary_search(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        raw_search_results = await self.http_get_request('http://api.urbandictionary.com/v0/define', params={
            'term': argument,
        })

        search_results = json.loads(raw_search_results)
        if not search_results['list']:
            return await message.channel.send(f'No results found for `{argument}`')

        result, *rest = search_results['list']
        definition = result["definition"].replace("[", "").replace("]", "")
        return await message.channel.send(
            f'**{result["word"]}**\n'
            f'<{result["permalink"]}>'
            f'\n'
            f'{definition}\n',
        )

    @command_handler('countdown')
    async def countdown(self, message: discord.Message, argument: str) -> None:
        if not argument.isdigit():
            return

        countdown_amount = int(argument)
        if countdown_amount < 1 or countdown_amount > 15:
            return

        for i in range(countdown_amount, 0, -1):
            await asyncio.gather(
                message.channel.send(f'{i}'),
                asyncio.sleep(1),
            )

        return await message.channel.send('DONE!')

    @command_handler('hello')
    async def greet(self, message: discord.Message, argument: str) -> None:
        return await message.channel.send(f'Hello {message.author.mention}')

    @command_handler('score')
    async def show_user_vote_score(self, message: discord.Message, argument: str):
        target_user = message.author
        if argument and message.mentions:
            target_user, *rest = message.mentions
            if rest:
                return

        score = await user_votes.get_score_for_user(target_user, message.guild)
        return await message.channel.send(f'{target_user.mention} has {plural(score, "point")}')

    @command_handler('lastspoke')
    async def show_user_last_spoke(self, message: discord.Message, argument: str):
        target_user = None
        if argument and message.mentions:
            target_user, *rest = message.mentions
            if rest:
                return
        if not target_user:
            return

        last_spoke = await user_stats.get_user_last_spoke(target_user, message.guild)
        if not last_spoke:
            return await message.channel.send(f"I don't have a record of {target_user.mention} ever speaking here")

        relative_seconds = readable_timedelta(datetime.utcnow() - last_spoke)
        return await message.channel.send(f"{target_user.mention} last spoke {relative_seconds}")

    async def vote_handler(self, message: discord.Message) -> None:
        # Ignore bot votes
        if message.author.bot:
            return

        point_value = {
            '++': +1,
            '--': -1,
        }

        # We clean content of codeblocks since they don't have real mentions
        clean_content = re.sub('`[^`]+`', '', re.sub('```.+```', '', message.content))

        # Since you can vote "multiple times" by chaining votes, we first aggregate by (voter,votee)->vote
        # before we deduplicate
        aggregated_votes: MutableMapping[discord.User, int] = defaultdict(int)
        for mentioned_user_id, action in re.findall(r'<@!?([0-9]+)>(\+\+|--)', clean_content):
            aggregated_votes[message.guild.get_member(int(mentioned_user_id))] += point_value[action]

        # Ignore self-voting
        has_self_vote = aggregated_votes.pop(message.author, None)
        if has_self_vote or not aggregated_votes:
            return

        await user_votes.add_votes(message, aggregated_votes)
        return await message.add_reaction('✅')

    @command_handler('stock')
    async def stock(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        argument = argument.upper()
        alpha_vantage_config = get_config_section('search.alpha-vantage')
        results = await self.http_get_request('https://www.alphavantage.co/query', params={
            'function': 'TIME_SERIES_DAILY',
            'symbol': argument,
            'apikey': alpha_vantage_config['api_key'],
        })

        json_results = json.loads(results)
        time_series = json_results.get('Time Series (Daily)', {})
        if not time_series:
            return await message.channel.send(f'No results found for `{argument}`')

        latest_time_stamp = max(time_series, key=datetime.fromisoformat)
        return await message.channel.send(f"**{argument}**: {time_series[latest_time_stamp]['4. close']}")

    @command_handler('metar')
    async def metar(self, message: discord.Message, argument: str) -> None:
        if not argument:
            return

        avwx_config = get_config_section('search.avwx')
        results = await self.http_get_request(f'https://avwx.rest/api/metar/{argument}', params={
            'format': 'json',
            'token': avwx_config['api_key']
        })

        json_results = json.loads(results)
        if 'error' in json_results:
            return await message.channel.send(f'```{json_results["error"]}```')

        return await message.channel.send(f'```{json_results["raw"]}```')

    @command_handler('conv')
    @command_handler('convert')
    async def convert(self, message: discord.Message, argument: str) -> None:
        aliases = {
            'inches': 'inch',
            'cm': 'centimeter',
            'centimeters': 'centimeter',
            'ft': 'feet',
            'c': 'celsius',
            'f': 'fahrenheit',
            'k': 'kelvin',
            'mi': 'miles',
            'km': 'kilometers',
            'lbs': 'pounds',
            'kg': 'kilograms',
            'g': 'grams',
        }

        conversions = {
            'feet': {
                'centimeter': lambda ft: ft * 30.48,
                'inch': lambda inch: inch * 12.0,
            },
            'inch': {
                'centimeter': lambda inch: inch * 2.54,
                'feet': lambda ft: ft / 12.0,
            },
            'centimeter': {
                'inch': lambda cm: cm / 2.54,
                'feet': lambda ft: ft / 30.48,
            },
            'fahrenheit': {
                'celsius': lambda c: (c - 32) * 5 / 9,
                'kelvin': lambda k: (k - 32) * 5 / 9 + 273.15,
            },
            'celsius': {
                'fahrenheit': lambda f: (f * 9 / 5) + 32,
                'kelvin': lambda k: k + 273.15,
            },
            'kelvin': {
                'fahrenheit': lambda f: (f - 273.15) * 9 / 5 + 32,
                'celsius': lambda c: c - 273.15,
            },
            'miles': {
                'kilometers': lambda km: km * 1.609344,
            },
            'kilometers': {
                'miles': lambda mi: mi / 1.609344,
            },
            'pounds': {
                'kilograms': lambda kg: kg / 2.2046226218,
                'grams': lambda g: g / 0.0022046,
            },
            'kilograms': {
                'pounds': lambda lbs: lbs * 2.2046226218,
                'grams': lambda g: g * 1000,
            },
            'grams': {
                'pounds': lambda lbs: lbs * 453.59237,
                'kilograms': lambda kg: kg / 1000,
            },
        }

        try:
            left, to_unit = re.split(r'\s+(?:to|in)\s+', argument, maxsplit=1)
            unit, from_unit = filter(None, re.split(r'(\-?\d+)\s*', left))

            to_unit = aliases.get(to_unit, to_unit)
            from_unit = aliases.get(from_unit, from_unit)
            return await message.channel.send(
                f'{unit} {from_unit} = {conversions[from_unit][to_unit](float(unit)):.2f} {to_unit}',
            )
        except (KeyError, ValueError):
            return await message.add_reaction('❓')

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        await asyncio.gather(
            self.vote_handler(message),
            user_stats.record_message(message),
            self.command_handler.process_message(self, message),
        )

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        # Only care about reactions to own messages
        if reaction.message.author != self.user:
            return

        if reaction.emoji == '🚫' and reaction.count >= 2:
            return await reaction.message.delete()

        quote_id_matches = re.search(r'Quote \*\*#(?P<quote_id>\d+)\*\* \(rated -?\d+\)', reaction.message.content)
        if quote_id_matches:
            quote_id = int(quote_id_matches['quote_id'])
            if self.is_rate_limited(user.id, 'quote.vote', quote_id):
                return

            if '👍' in reaction.emoji:
                self.record_action(user.id, 'quote.vote', quote_id)
                return await quotes.modify_quote_score(quote_id, +1)
            if '👎' in reaction.emoji:
                self.record_action(user.id, 'quote.vote', quote_id)
                return await quotes.modify_quote_score(quote_id, -1)

    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User) -> None:
        # Only care about reactions to own messages
        if reaction.message.author != self.user:
            return

        quote_id_matches = re.search(r'Quote \*\*#(?P<quote_id>\d+)\*\* \(rated -?\d+\)', reaction.message.content)
        if quote_id_matches:
            quote_id = int(quote_id_matches['quote_id'])

            if '👍' in reaction.emoji:
                return await quotes.modify_quote_score(quote_id, -1)
            if '👎' in reaction.emoji:
                return await quotes.modify_quote_score(quote_id, +1)
