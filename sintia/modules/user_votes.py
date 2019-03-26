from typing import Mapping

import discord

from sintia.mysql import query_single, query_many_commit


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

