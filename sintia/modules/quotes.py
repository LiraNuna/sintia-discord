import re
from datetime import datetime
from typing import NamedTuple, Optional, Dict, List

import aiomysql

from sintia.config import get_config_section
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


@memoize
async def get_connection_pool():
    qdb_config = get_config_section('quotes')
    return await aiomysql.create_pool(
        host=qdb_config['hostname'],
        port=qdb_config.getint('post', 3306),
        user=qdb_config['username'],
        password=qdb_config['password'],
        db=qdb_config['database'],
    )


async def query_single(query: str, *args) -> Optional[Dict]:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchone()


async def query_all(query: str, *args) -> Optional[List[Dict]]:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchall()


async def get_quote(id: int) -> Optional[Quote]:
    quote = await query_single("SELECT * FROM quotes WHERE id = %s", id)
    if not quote:
        return None

    return Quote(**quote)


async def get_random_quote() -> Quote:
    quote = await query_single("SELECT * FROM quotes ORDER BY RAND() LIMIT 1")
    return Quote(**quote)


async def get_latest_quote(containing: str = '') -> Optional[Quote]:
    quote = await query_single("SELECT * FROM quotes WHERE quote LIKE %s ORDER BY id DESC LIMIT 1", f'%{containing}%')
    if not quote:
        return None

    return Quote(**quote)


async def get_best_quote() -> Quote:
    quote = await query_single("SELECT * FROM quotes ORDER BY score DESC LIMIT 1")
    return Quote(**quote)


async def get_quote_rank(quote_id: int) -> int:
    result = await query_single("""
        SELECT COUNT(DISTINCT(score)) + 1 AS rank
        FROM quotes
        WHERE score > (SELECT score FROM quotes WHERE id = %s)
    """, quote_id)

    return int(result['rank'])


async def get_quotes_for_rank(rank: int) -> List[Quote]:
    quotes = await query_all("""
        SELECT * FROM quotes WHERE score = (
            SELECT score FROM quotes GROUP BY score ORDER BY score DESC LIMIT %s,1
        ) ORDER BY id ASC
    """, rank)

    return [Quote(**quote) for quote in quotes]


async def find_quotes_by_search_term(search_term: str) -> List[Quote]:
    quotes = await query_all(
        "SELECT * FROM quotes WHERE quote LIKE %s ORDER BY id ASC",
        f'%{search_term}%',
    )

    return [Quote(**quote) for quote in quotes]


async def add_quote(creator: str, quote: str, addchannel: str) -> int:
    latest_quote = await get_latest_quote()
    new_quote_id = latest_quote.id + 1

    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                INSERT INTO quotes (id, creator, quote, addchannel) VALUES (%s, %s, %s, %s)
            """, (new_quote_id, creator, quote, addchannel))

            await connection.commit()

    return new_quote_id


async def modify_quote_score(quote_id: int, amount: int):
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("UPDATE quotes SET score = score + %s WHERE id = %s", (amount, quote_id))
            await connection.commit()
