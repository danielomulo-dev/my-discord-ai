import os
import threading
import re
import asyncio
import dateparser
from datetime import datetime
from flask import Flask
import discord
from discord.ext import tasks # <--- Needed for the loop
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
def home(): return "Emily is Online with Alarm Clock!"
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
    # Start the background clock check
    if not check_reminders_loop.is_running():
        check_reminders_loop.start()

# --- BACKGROUND TASK: CHECK REMINDERS EVERY 60 SECONDS ---
@tasks.loop(seconds=60)
async def check_reminders_loop():
    try:
        # Get list of reminders that are due right now
        due_list = get_due_reminders()
        
        for reminder in due_list:
            channel_id = reminder['channel_id']
            user_id = reminder['user_id']
            text = reminder['text']
            
            # Send the message
            channel = client.get_channel(int(channel_id))
            if channel:
                await channel.send(f"🔔 **REMINDER:** <@{user_id}> {text}")
                print(f"Sent reminder to {user_id}")
            
            # Delete from DB so we don't send it twice
            delete_reminder(reminder['_id'])
            
    except Exception as e:
        print(f"Loop Error: {e}")

@client.event
async def on_message(message):
    if message.author == client.user: return

    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 1. PROCESS LINKS & FILES (Same as before)
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            scraped_content = extract_text_from_url(urls[0])
            user_text += f"\n\n{scraped_content}"

        doc_text = ""
        image_data = None
        
        if message.attachments:
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    image_bytes = await attachment.read()
                    image_data = {"mime_type": attachment.content_type, "data": image_bytes}
                elif filename.endswith('.pdf'):
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)
                elif filename.endswith('.docx'):
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)
        
        if doc_text: user_text += f"\n\n{doc_text}"

        # 2. SAVE TO HISTORY
        new_message_parts = [{"text": user_text}]
        if image_data: new_message_parts.append({"inline_data": image_data})
        add_message_to_history(user_id, "user", new_message_parts)

        # 3. GET RESPONSE
        history = get_chat_history(user_id)
        
        async with message.channel.typing():
            response_text = await get_ai_response(history, user_id)
            
            # --- CHECK FOR REMINDER TAG ---
            # [REMIND: tomorrow at 4pm | check budget]
            remind_match = re.search(r'\[REMIND: (.*?) \| (.*?)\]', response_text, re.IGNORECASE)
            if remind_match:
                time_str = remind_match.group(1)
                task_str = remind_match.group(2)
                
                # Convert "tomorrow at 4pm" to real computer time
                # settings={'PREFER_DATES_FROM': 'future'} helps it understand we mean the future
                real_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
                
                if real_time:
                    add_reminder(user_id, message.channel.id, real_time, task_str)
                    print(f"Reminder set for: {real_time}")
                    # Remove the tag from the message so user doesn't see the code
                    response_text = response_text.replace(remind_match.group(0), f"✅ *Alarm set for {time_str}*")
                else:
                    response_text = response_text.replace(remind_match.group(0), "❌ *I couldn't understand that time.*")

            # Save Model Response
            add_message_to_history(user_id, "model", [{"text": response_text}])

            # Send Message
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.channel.send(response_text[i:i+2000])
            else:
                await message.channel.send(response_text)

if __name__ == "__main__":
    t = threading.Thread(target=run_web_server)
    t.start()
    client.run(os.getenv("DISCORD_TOKEN"))