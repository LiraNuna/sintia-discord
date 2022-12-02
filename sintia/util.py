from __future__ import annotations

import asyncio
import inspect
from collections import Iterable
from datetime import timedelta
from functools import lru_cache
from itertools import islice
from typing import Awaitable
from typing import Mapping
from typing import TypeVar

T = TypeVar('T')
Tk = TypeVar('Tk')
Tv = TypeVar('Tv')


def memoize(user_function):
    def interceptor(*args, **kwargs):
        result = user_function(*args, **kwargs)
        if inspect.isawaitable(result):
            return asyncio.ensure_future(result)

        return result

    return lru_cache(maxsize=None)(interceptor)


def ordinal(position: int) -> str:
    return "%d%s" % (position, "tsnrhtdd"[(position // 10 % 10 != 1) * (position % 10 < 4) * position % 10::4])


def plural(count: int, thing: str) -> str:
    if count == 1:
        return f'1 {thing}'

    return f'{count} {thing}s'


def readable_timedelta(delta: timedelta) -> str:
    periods = {
        'year': delta.days // 365,
        'month': delta.days // 30,
        'week': delta.days // 7,
        'day': delta.days % 30,
        'hour': delta.seconds // 3600,
        'minute': delta.seconds // 60,
        'second': delta.seconds % 60,
    }

    for period in periods.keys():
        n = periods[period]
        if n > 0:
            return plural(n, period) + ' ago'

    return 'just now'


def ichunk(iterable: Iterable[T], chunk_size: int) -> Iterable[list[T]]:
    """
    Split up iterable into chunk_size lists
    """
    i = iter(iterable)
    while chunk := list(islice(i, chunk_size)):
        yield chunk


async def gather_mapping(mapping: Mapping[Tk, Awaitable[Tv]]) -> Mapping[Tk, Tv]:
    """Resolves a mapping of {Tk, Awaitable[Tv]} to {Tk, Tv}"""

    items = list(mapping.items())
    keys = (key for key, value in items)
    values = await asyncio.gather(*(value for key, value in items))

    return dict(zip(keys, values))
