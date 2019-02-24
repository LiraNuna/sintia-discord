import asyncio
import inspect
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
