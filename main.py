import os
import threading
import re
import asyncio
import dateparser
from datetime import datetime
from flask import Flask
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# Import Tools
from ai_brain import get_ai_response
from web_tools import extract_text_from_url
from file_tools import extract_text_from_pdf, extract_text_from_docx
from memory import add_message_to_history, get_chat_history, add_reminder, get_due_reminders, delete_reminder

load_dotenv()

# --- Web Server ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily is Online with Ears!"
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
    if not check_reminders_loop.is_running():
        check_reminders_loop.start()

@tasks.loop(seconds=60)
async def check_reminders_loop():
    try:
        due_list = get_due_reminders()
        for reminder in due_list:
            channel = client.get_channel(int(reminder['channel_id']))
            if channel:
                await channel.send(f"🔔 **REMINDER:** <@{reminder['user_id']}> {reminder['text']}")
            delete_reminder(reminder['_id'])
    except Exception as e:
        print(f"Loop Error: {e}")

@client.event
async def on_message(message):
    if message.author == client.user: return

    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 1. PROCESS LINKS
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            scraped_content = extract_text_from_url(urls[0])
            user_text += f"\n\n{scraped_content}"

        # 2. PROCESS ATTACHMENTS (Images, Files, AND NOW AUDIO)
        media_data = None # Can be image OR audio
        doc_text = ""

        if message.attachments:
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                
                # A. IMAGES
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    image_bytes = await attachment.read()
                    media_data = {"mime_type": attachment.content_type, "data": image_bytes}
                
                # B. AUDIO (Voice Notes) - NEW FEATURE
                elif filename.endswith(('.ogg', '.mp3', '.wav', '.m4a')):
                    print(f"👂 Audio detected: {filename}")
                    await message.channel.send("👂 *Listening to your voice note...*")
                    audio_bytes = await attachment.read()
                    # Discord usually sends voice notes as audio/ogg
                    media_data = {"mime_type": attachment.content_type or "audio/ogg", "data": audio_bytes}

                # C. DOCUMENTS
                elif filename.endswith('.pdf'):
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)
                elif filename.endswith('.docx'):
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)
        
        if doc_text: user_text += f"\n\n{doc_text}"

        # 3. SAVE TO HISTORY
        new_message_parts = [{"text": user_text}]
        if media_data: 
            new_message_parts.append({"inline_data": media_data})
        
        add_message_to_history(user_id, "user", new_message_parts)

        # 4. GET RESPONSE
        history = get_chat_history(user_id)
        
        async with message.channel.typing():
            response_text = await get_ai_response(history, user_id)
            
            # Check for Reminders tag
            remind_match = re.search(r'\[REMIND: (.*?) \| (.*?)\]', response_text, re.IGNORECASE)
            if remind_match:
                time_str = remind_match.group(1)
                task_str = remind_match.group(2)
                real_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
                if real_time:
                    add_reminder(user_id, message.channel.id, real_time, task_str)
                    response_text = response_text.replace(remind_match.group(0), f"✅ *Alarm set for {time_str}*")
                else:
                    response_text = response_text.replace(remind_match.group(0), "❌ *Time not understood.*")

            add_message_to_history(user_id, "model", [{"text": response_text}])

            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.channel.send(response_text[i:i+2000])
            else:
                await message.channel.send(response_text)

if __name__ == "__main__":
    t = threading.Thread(target=run_web_server)
    t.start()
    client.run(os.getenv("DISCORD_TOKEN"))