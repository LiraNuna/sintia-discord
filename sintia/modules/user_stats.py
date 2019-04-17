from datetime import datetime

import discord

from sintia.mysql import query_single_commit, query_single


async def record_message(message: discord.Message) -> None:
    await query_single_commit(
        """
        INSERT INTO user_activity_history (guild_id, channel_id, user_id, last_spoke_at)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE last_spoke_at = %s
        """,
        message.guild.id, message.channel.id, message.author.id, message.created_at, message.created_at,
    )


async def record_command(message: discord.Message, command: str) -> None:
    await query_single_commit(
        """
        INSERT INTO command_activity_history (invoked_at, guild_id, channel_id, user_id, command)
        VALUES (%s, %s, %s, %s, %s)
        """,
        message.created_at, message.guild.id, message.channel.id, message.author.id, command,
    )


async def get_user_last_spoke(user: discord.User, guild: discord.Guild) -> datetime:
    row = await query_single(
        """
        SELECT MAX(last_spoke_at) AS last_spoke_at
        FROM user_activity_history
        WHERE guild_id = %s AND user_id = %s
        """,
        guild.id, user.id,
    )

    return row['last_spoke_at']
