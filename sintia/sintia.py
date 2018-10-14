import os
import discord


class Sintia(discord.Client):
    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        # Hello world!
        if message.content.startswith('!hello'):
            await message.channel.send(f'Hello {message.author.mention}')


sintia = Sintia()
sintia.run(os.environ['DISCORD_TOKEN'])
