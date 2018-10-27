import asyncio
import inspect
from itertools import tee
from functools import lru_cache


def memoize(user_function):
    def interceptor(*args, **kwargs):
        result = user_function(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return asyncio.ensure_future(result)
        if inspect.isgenerator(result):
            return tee(result)

        return result

    return lru_cache(maxsize=None)(interceptor)
