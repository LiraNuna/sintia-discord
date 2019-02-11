from typing import Mapping

import aiomysql
import discord

from sintia.config import get_config_section
from sintia.util import memoize


@memoize
async def get_connection_pool():
    qdb_config = get_config_section('user_votes')
    return await aiomysql.create_pool(
        host=qdb_config['hostname'],
        port=qdb_config.getint('post', 3306),
        user=qdb_config['username'],
        password=qdb_config['password'],
        db=qdb_config['database'],
    )


async def add_votes(message: discord.Message, votes: Mapping[discord.User, int]) -> None:
    votes = [
        (message.guild.id, message.id, voted_user.id, message.author.id, score)
        for voted_user, score in votes.items()
        if score != 0
    ]

    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.executemany("""
                INSERT INTO user_votes (guild_id, message_id, voted_user_id, voting_user_id, points_delta) 
                VALUES (%s, %s, %s, %s, %s)
            """, votes)

            await connection.commit()


async def get_score_for_user(user: discord.User, guild: discord.Guild) -> int:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT COALESCE(SUM(points_delta), 0) AS score 
                FROM user_votes 
                WHERE guild_id = %s AND voted_user_id = %s
            """, (guild.id, user.id))
            row = await cursor.fetchone()
            return row['score']
