import os
import discord
from dotenv import load_dotenv
from ai_brain import get_ai_response

# Load environment variables
load_dotenv()

# Setup Discord Intents
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Discord Bot logged in as {client.user}')

@client.event
async def on_message(message):
    # Don't let the bot reply to itself
    if message.author == client.user:
        return

    # Check if the bot is mentioned or DM'd
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        # Remove the mention from the prompt (e.g. <@123456>) to avoid confusing the AI
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # Show "typing..." status while generating response
        async with message.channel.typing():
            response = await get_ai_response(user_text)
            
            # Discord has a 2000 char limit, split if needed
            if len(response) > 2000:
                for i in range(0, len(response), 2000):
                    await message.channel.send(response[i:i+2000])
            else:
                await message.channel.send(response)

# Run the bot
client.run(os.getenv("DISCORD_TOKEN"))