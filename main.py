import os
import threading
import re
import asyncio
from flask import Flask
import discord
from dotenv import load_dotenv

# Import our tools
from ai_brain import get_ai_response
from web_tools import extract_text_from_url
from file_tools import extract_text_from_pdf, extract_text_from_docx

load_dotenv()

# --- Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily is Online!"
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- MEMORY ---
user_memory = {}

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
        
        # 1. CHECK FOR LINKS
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            await message.channel.send(f"👀 Checking that link: {urls[0]}...")
            scraped_content = extract_text_from_url(urls[0])
            user_text += f"\n\n{scraped_content}"

        # 2. CHECK FOR ATTACHMENTS (Images, PDFs, Docs)
        image_data = None
        doc_text = ""

        if message.attachments:
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                
                # CASE A: IMAGE
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    print(f"Image found: {filename}")
                    image_bytes = await attachment.read()
                    image_data = {
                        "mime_type": attachment.content_type,
                        "data": image_bytes
                    }
                
                # CASE B: PDF
                elif filename.endswith('.pdf'):
                    print(f"PDF found: {filename}")
                    await message.channel.send("📄 Reading PDF...")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)

                # CASE C: WORD DOC
                elif filename.endswith('.docx'):
                    print(f"Word Doc found: {filename}")
                    await message.channel.send("📝 Reading Word Doc...")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)

        # Append document text to the user's message
        if doc_text:
            user_text += f"\n\n{doc_text}"

        # 3. PREPARE MEMORY
        if user_id not in user_memory: user_memory[user_id] = []

        # Construct the message payload
        new_message_parts = [{"text": user_text}]
        
        # If we found an image, add it
        if image_data:
            new_message_parts.append({"inline_data": image_data})

        user_memory[user_id].append({
            "role": "user", 
            "parts": new_message_parts
        })

        # Limit Memory
        if len(user_memory[user_id]) > 20:
            user_memory[user_id] = user_memory[user_id][-20:]

        # 4. GET RESPONSE
        async with message.channel.typing():
            # Pass user_id so she can access Long-Term Memory
            response_text = await get_ai_response(user_memory[user_id], user_id)
            
            user_memory[user_id].append({
                "role": "model",
                "parts": [{"text": response_text}]
            })

            # Send Split Message
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