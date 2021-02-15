from __future__ import annotations

from typing import Type, Optional, TypeVar

import aiomysql

from sintia.config import get_config_section
from sintia.util import memoize

T = TypeVar('T')


@memoize
async def get_connection_pool():
    qdb_config = get_config_section('mysql')
    return await aiomysql.create_pool(
        host=qdb_config['hostname'],
        port=qdb_config.getint('post', 3306),
        user=qdb_config['username'],
        password=qdb_config['password'],
        db=qdb_config['database'],
    )


async def query_single(query: str, *args, result_type: Type[T] = dict) -> Optional[T]:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)

            row = await cursor.fetchone()
            if not row:
                return None

            return result_type(**row)


async def query_all(query: str, *args, result_type: Type[T] = dict) -> list[T]:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)

            return [result_type(**row) async for row in cursor]


async def query_single_commit(query: str, *args) -> None:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)
            await connection.commit()


async def query_many_commit(query: str, *args) -> None:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.executemany(query, args)
            await connection.commit()
