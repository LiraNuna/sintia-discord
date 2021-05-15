from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

import discord

from sintia.mysql import query_single
from sintia.mysql import query_single_commit


class ActivityRecord(NamedTuple):
    guild_id: int
    channel_id: int
    user_id: int
    last_spoke_at: datetime


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


async def get_user_last_activity(user: discord.User, guild: discord.Guild) -> ActivityRecord:
    return await query_single(
        """
        SELECT *
        FROM user_activity_history
        WHERE guild_id = %s AND user_id = %s
        ORDER BY last_spoke_at DESC
        LIMIT 1
        """,
        guild.id, user.id,
        result_type=ActivityRecord,
    )
