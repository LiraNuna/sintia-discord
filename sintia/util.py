import asyncio
import inspect
from datetime import timedelta
from functools import lru_cache


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
