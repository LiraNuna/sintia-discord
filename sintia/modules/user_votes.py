from __future__ import annotations

from collections import Mapping
from typing import Union

import discord

from sintia.mysql import query_all
from sintia.mysql import query_many_commit
from sintia.mysql import query_single
from sintia.mysql import query_single_commit


async def add_votes(message: discord.Message, votes: Mapping[discord.User, int]) -> None:
    votes = [
        (message.guild.id, message.id, voted_user.id, message.author.id, score)
        for voted_user, score in votes.items()
        if score != 0
    ]

    await query_many_commit(
        """
        INSERT INTO user_votes (guild_id, message_id, voted_user_id, voting_user_id, points_delta) 
        VALUES (%s, %s, %s, %s, %s)
        """,
        *votes,
    )


async def get_score_for_user(user: discord.User, guild: discord.Guild) -> int:
    row = await query_single(
        """
        SELECT COALESCE(SUM(points_delta), 0) AS score 
        FROM user_votes 
        WHERE guild_id = %s AND voted_user_id = %s
        """,
        guild.id,
        user.id,
    )

    return row['score']


async def add_emoji_vote(
    user: discord.User,
    guild: discord.Guild,
    emoji: Union[str, discord.Emoji, discord.PartialEmoji],
    delta: int,
) -> None:
    if isinstance(emoji, discord.PartialEmoji):
        return

    await query_single_commit(
        """
        INSERT INTO user_emoji_votes (guild_id, user_id, emoji, amount) 
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        amount = amount + %s
        """,
        guild.id, user.id, str(emoji), 1, delta,
    )


async def get_emoji_score_for_user(guild: discord.Guild, user: discord.User, limit: int = 3) -> dict[str, int]:
    rows = await query_all(
        """
        SELECT emoji, amount 
        FROM user_emoji_votes 
        WHERE guild_id = %s AND user_id = %s
        ORDER BY amount DESC, updated_at 
        LIMIT %s;
        """,
        guild.id, user.id, limit,
    )

    return {
        row['emoji']: row['amount']
        for row in rows
    }
