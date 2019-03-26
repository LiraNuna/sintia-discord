import re
from datetime import datetime
from typing import NamedTuple, Optional, List

from sintia.mysql import query_single_commit, query_all, query_single


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


async def get_quote(id: int) -> Optional[Quote]:
    return await query_single(
        "SELECT * FROM quotes WHERE id = %s",
        id,
        result_type=Quote,
    )


async def get_random_quote() -> Quote:
    return await query_single(
        "SELECT * FROM quotes ORDER BY RAND() LIMIT 1",
        result_type=Quote,
    )


async def get_latest_quote(containing: str = '') -> Optional[Quote]:
    return await query_single(
        "SELECT * FROM quotes WHERE quote LIKE %s ORDER BY id DESC LIMIT 1",
        f'%{containing}%',
        result_type=Quote,
    )


async def get_best_quote() -> Quote:
    return await query_single(
        "SELECT * FROM quotes ORDER BY score DESC LIMIT 1",
        result_type=Quote,
    )


async def get_quote_rank(quote_id: int) -> int:
    result = await query_single(
        """
        SELECT COUNT(DISTINCT(score)) + 1 AS quote_rank
        FROM quotes
        WHERE score > (SELECT score FROM quotes WHERE id = %s)
        """,
        quote_id,
    )

    return int(result['quote_rank'])


async def get_quotes_for_rank(rank: int) -> List[Quote]:
    return await query_all(
        """
        SELECT * FROM quotes WHERE score = (
            SELECT score FROM quotes GROUP BY score ORDER BY score DESC LIMIT %s,1
        ) ORDER BY id ASC
        """,
        rank,
        result_type=Quote,
    )


async def find_quotes_by_search_term(search_term: str) -> List[Quote]:
    return await query_all(
        "SELECT * FROM quotes WHERE quote LIKE %s ORDER BY id ASC",
        f'%{search_term}%',
        result_type=Quote,
    )


async def add_quote(creator: str, quote: str, addchannel: str) -> int:
    latest_quote = await get_latest_quote()
    new_quote_id = latest_quote.id + 1

    await query_single_commit(
        "INSERT INTO quotes (id, creator, quote, addchannel) VALUES (%s, %s, %s, %s)",
        new_quote_id, creator, quote, addchannel,
    )

    return new_quote_id


async def modify_quote_score(quote_id: int, amount: int):
    await query_single_commit("UPDATE quotes SET score = score + %s WHERE id = %s", amount, quote_id)
