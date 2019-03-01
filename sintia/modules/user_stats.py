from datetime import datetime

import aiomysql
import discord

from sintia.config import get_config_section
from sintia.util import memoize


@memoize
async def get_connection_pool():
    qdb_config = get_config_section('user_stats')
    return await aiomysql.create_pool(
        host=qdb_config['hostname'],
        port=qdb_config.getint('post', 3306),
        user=qdb_config['username'],
        password=qdb_config['password'],
        db=qdb_config['database'],
    )


async def record_message(message: discord.Message) -> None:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                INSERT INTO user_activity_history (guild_id, channel_id, user_id, last_spoke_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE last_spoke_at = %s
            """, (message.guild.id, message.channel.id, message.author.id, message.created_at, message.created_at))

            await connection.commit()


async def get_user_last_spoke(user: discord.User, guild: discord.Guild) -> datetime:
    qdb_pool = await get_connection_pool()
    async with qdb_pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT MAX(last_spoke_at) AS last_spoke_at
                FROM user_activity_history
                WHERE guild_id = %s AND user_id = %s
            """, (guild.id, user.id))
            row = await cursor.fetchone()

            return row['last_spoke_at']
