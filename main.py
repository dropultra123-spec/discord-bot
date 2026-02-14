import discord
import os

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Бот запущен как {client.user}')

@client.event
async def on_message(message):
    if message.content == "!ping":
        await message.channel.send("Pong!")

client.run(os.getenv("TOKEN"))
