import os
import threading
from flask import Flask
import discord
from dotenv import load_dotenv
from ai_brain import get_ai_response

load_dotenv()

# --- Web Server (To keep the bot alive on the cloud) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is Alive!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- Discord Bot Logic ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    # Check if mentioned or DM
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        async with message.channel.typing():
            response = await get_ai_response(user_text)
            if len(response) > 2000:
                for i in range(0, len(response), 2000):
                    await message.channel.send(response[i:i+2000])
            else:
                await message.channel.send(response)

# --- Start Everything ---
if __name__ == "__main__":
    # 1. Start the web server in the background
    t = threading.Thread(target=run_web_server)
    t.start()
    
    # 2. Start the Discord bot
    client.run(os.getenv("DISCORD_TOKEN"))