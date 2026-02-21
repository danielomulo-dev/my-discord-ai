import os
import threading
import re
import asyncio
from flask import Flask
import discord
from dotenv import load_dotenv

# Import Tools
from ai_brain import get_ai_response
from web_tools import extract_text_from_url
from file_tools import extract_text_from_pdf, extract_text_from_docx
# Import the NEW Memory Functions
from memory import add_message_to_history, get_chat_history

load_dotenv()

# --- Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily is Online with Persistent Memory!"
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
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
        
        # 1. PROCESS LINKS
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            await message.channel.send(f"👀 Checking link: {urls[0]}...")
            scraped_content = extract_text_from_url(urls[0])
            user_text += f"\n\n{scraped_content}"

        # 2. PROCESS ATTACHMENTS
        image_data = None
        doc_text = ""

        if message.attachments:
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                
                # Images
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    image_bytes = await attachment.read()
                    image_data = {
                        "mime_type": attachment.content_type,
                        "data": image_bytes
                    }
                
                # Docs
                elif filename.endswith('.pdf'):
                    await message.channel.send("📄 Reading PDF...")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)
                elif filename.endswith('.docx'):
                    await message.channel.send("📝 Reading Word Doc...")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)

        if doc_text:
            user_text += f"\n\n{doc_text}"

        # 3. SAVE USER MESSAGE TO MONGODB
        # Construct message parts
        new_message_parts = [{"text": user_text}]
        if image_data:
            new_message_parts.append({"inline_data": image_data})

        add_message_to_history(user_id, "user", new_message_parts)

        # 4. LOAD HISTORY FROM MONGODB
        history = get_chat_history(user_id)

        # 5. GET RESPONSE
        async with message.channel.typing():
            response_text = await get_ai_response(history, user_id)
            
            # Save Emily's response to MongoDB
            add_message_to_history(user_id, "model", [{"text": response_text}])

            # Send to Discord
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.channel.send(response_text[i:i+2000])
            else:
                await message.channel.send(response_text)

if __name__ == "__main__":
    t = threading.Thread(target=run_web_server)
    t.start()
    client.run(os.getenv("DISCORD_TOKEN"))