import os
import threading
import asyncio
from flask import Flask
import discord
from dotenv import load_dotenv
from ai_brain import get_ai_response

load_dotenv()

# --- Web Server (To keep the bot alive on Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot with Vision is Alive!"

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
    # Don't let the bot reply to itself
    if message.author == client.user:
        return
    
    # Check if mentioned or DM
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        # 1. Clean the text (remove the @mention)
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 2. Prepare variables for image
        image_bytes = None
        mime_type = None

        # 3. Check for attachments (Images)
        if message.attachments:
            # Get the first attachment
            attachment = message.attachments[0]
            
            # Check if it is an image
            if attachment.content_type and attachment.content_type.startswith('image/'):
                print(f"Downloading image: {attachment.filename}")
                image_bytes = await attachment.read()
                mime_type = attachment.content_type
            else:
                # If they attach a PDF or Zip, ignore it
                pass

        # 4. Send to Brain
        async with message.channel.typing():
            response = await get_ai_response(user_text, image_bytes, mime_type)
            
            # 5. Send response (Discord has a 2000 char limit, split if needed)
            if len(response) > 2000:
                for i in range(0, len(response), 2000):
                    await message.channel.send(response[i:i+2000])
            else:
                await message.channel.send(response)

# --- Start Everything ---
if __name__ == "__main__":
    # Start the web server in a background thread
    t = threading.Thread(target=run_web_server)
    t.start()
    
    # Start the Discord bot
    client.run(os.getenv("DISCORD_TOKEN"))