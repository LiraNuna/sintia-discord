from configparser import ConfigParser

import discord


class Sintia(discord.Client):
    config: ConfigParser

    def __init__(self, config: ConfigParser) -> None:
        super().__init__()

        self.config = config

    def run(self):
        super().run(self.config['discord']['token'])

    async def on_ready(self) -> None:
        print(f'Logged in as {self.user.name} ({self.user.id})')

    async def on_message(self, message: discord.Message) -> None:
        # Avoid replying to self
        if message.author == self.user:
            return

        # Hello world!
        if message.content == '!hello':
            await message.channel.send(f'Hello {message.author.mention}')
