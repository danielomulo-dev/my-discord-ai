import os
import threading
import asyncio
from flask import Flask
import discord
from dotenv import load_dotenv
from ai_brain import get_ai_response

load_dotenv()

# --- Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily with Memory is Alive!"
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- MEMORY STORAGE ---
# Dictionary to store history: { user_id: [message_list] }
user_memory = {}

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

    # Check for DM or Mention
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()

        # 1. Initialize memory for this user if they are new
        if user_id not in user_memory:
            user_memory[user_id] = []

        # 2. Add USER message to memory
        # Handle images if attached
        if message.attachments and message.attachments[0].content_type.startswith('image/'):
            print("Image detected")
            image_bytes = await message.attachments[0].read()
            mime_type = message.attachments[0].content_type
            
            # Add text AND image to history
            user_memory[user_id].append({
                "role": "user", 
                "parts": [
                    {"text": user_text},
                    {"inline_data": {"mime_type": mime_type, "data": image_bytes}}
                ]
            })
        else:
            # Just text
            user_memory[user_id].append({
                "role": "user", 
                "parts": [user_text]
            })

        # 3. Limit Memory (Keep last 20 messages to save cost/speed)
        if len(user_memory[user_id]) > 20:
            user_memory[user_id] = user_memory[user_id][-20:]

        # 4. Send History to Brain & Get Response
        async with message.channel.typing():
            response_text = await get_ai_response(user_memory[user_id])
            
            # 5. Add EMILY'S response to memory
            user_memory[user_id].append({
                "role": "model",
                "parts": [response_text]
            })

            # 6. Send to Discord
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.channel.send(response_text[i:i+2000])
            else:
                await message.channel.send(response_text)

# --- Start ---
if __name__ == "__main__":
    t = threading.Thread(target=run_web_server)
    t.start()
    client.run(os.getenv("DISCORD_TOKEN"))