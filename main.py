import os
import threading
import re
from flask import Flask
import discord
from dotenv import load_dotenv
from ai_brain import get_ai_response
from web_tools import extract_text_from_url  # <--- Import our new tool

load_dotenv()

# --- Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily with Internet Access is Alive!"
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- MEMORY STORAGE ---
user_memory = {}

# --- Discord Bot Logic ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Regex to find URLs in messages
URL_PATTERN = r'(https?://\S+)'

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user: return

    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 1. CHECK FOR LINKS IN THE MESSAGE
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            await message.channel.send("👀 I see a link! Reading it now...")
            # Pick the first link and read it
            scraped_content = extract_text_from_url(urls[0])
            # Append the scraped content to the user's message so Emily "knows" it
            user_text += f"\n\n{scraped_content}"

        # 2. Initialize Memory
        if user_id not in user_memory:
            user_memory[user_id] = []

        # 3. Handle Images or Text
        if message.attachments and message.attachments[0].content_type.startswith('image/'):
            image_bytes = await message.attachments[0].read()
            mime_type = message.attachments[0].content_type
            user_memory[user_id].append({
                "role": "user", 
                "parts": [
                    {"text": user_text},
                    {"inline_data": {"mime_type": mime_type, "data": image_bytes}}
                ]
            })
        else:
            user_memory[user_id].append({
                "role": "user", 
                "parts": [user_text]
            })

        # Limit Memory
        if len(user_memory[user_id]) > 20:
            user_memory[user_id] = user_memory[user_id][-20:]

        # 4. Generate Response
        async with message.channel.typing():
            response_text = await get_ai_response(user_memory[user_id], user_id)
            
            user_memory[user_id].append({
                "role": "model",
                "parts": [response_text]
            })

            # Send Split Message if too long
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