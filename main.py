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

# --- CUSTOM TOOLS IMPORTS ---
from ai_brain import get_ai_response
from web_tools import extract_text_from_url
from file_tools import extract_text_from_pdf, extract_text_from_docx
from memory import (
    add_message_to_history, 
    get_chat_history, 
    add_reminder, 
    get_due_reminders, 
    delete_reminder, 
    get_user_profile, 
    set_voice_mode
)
from voice_tools import generate_voice_note, cleanup_voice_file

load_dotenv()

# --- WEB SERVER (Keep-Alive for Render) ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Emily is Online! (Voice, Memory, & Alarms Active)"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
URL_PATTERN = r'(https?://\S+)'

@client.event
async def on_ready():
    print(f'✅ Logged in as {client.user}')
    # Start the background clock for reminders
    # This also helps keep the connection alive
    if not check_reminders_loop.is_running():
        check_reminders_loop.start()

# --- BACKGROUND TASK: ALARM CLOCK ---
@tasks.loop(seconds=60)
async def check_reminders_loop():
    try:
        due_list = get_due_reminders()
        for reminder in due_list:
            channel = client.get_channel(int(reminder['channel_id']))
            if channel:
                await channel.send(f"🔔 **REMINDER:** <@{reminder['user_id']}> {reminder['text']}")
                print(f"Sent reminder to {reminder['user_id']}")
            
            # Delete from DB so we don't send it twice
            delete_reminder(reminder['_id'])
    except Exception as e:
        print(f"Loop Error: {e}")

# --- MAIN MESSAGE HANDLER ---
@client.event
async def on_message(message):
    # Don't talk to yourself
    if message.author == client.user: return

    # --- COMMANDS: VOICE TOGGLE ---
    if message.content.lower() == "!voice on":
        set_voice_mode(message.author.id, True)
        await message.channel.send("🎙️ **Voice Mode Activated!** I will now speak my responses.")
        return
    
    if message.content.lower() == "!voice off":
        set_voice_mode(message.author.id, False)
        await message.channel.send("📝 **Voice Mode Deactivated.** Back to text only.")
        return

    # --- CONVERSATION LOGIC ---
    # Only reply if DM'd or Mentioned
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        # Remove the @mention from the text so she doesn't read it
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 1. CHECK VOICE PREFERENCE
        # Load profile to see if Voice Mode is ON
        profile = get_user_profile(user_id)
        should_speak = profile.get("voice_mode", False) # Default is False (Off)

        # 2. PROCESS LINKS (Web Scraping)
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            await message.channel.send(f"👀 *Checking link...*")
            scraped_content = extract_text_from_url(urls[0])
            user_text += f"\n\n{scraped_content}"

        # 3. PROCESS ATTACHMENTS (Images, Audio, Docs)
        media_data = None
        doc_text = ""

        if message.attachments:
            for attachment in message.attachments:
                filename = attachment.filename.lower()
                
                # A. IMAGES
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    image_bytes = await attachment.read()
                    media_data = {"mime_type": attachment.content_type, "data": image_bytes}
                
                # B. AUDIO (Voice Notes)
                elif filename.endswith(('.ogg', '.mp3', '.wav', '.m4a')):
                    print(f"👂 Audio detected: {filename}")
                    await message.channel.send("👂 *Listening...*")
                    audio_bytes = await attachment.read()
                    media_data = {"mime_type": attachment.content_type or "audio/ogg", "data": audio_bytes}
                    should_speak = True # Force voice reply if user speaks
                
                # C. DOCUMENTS
                elif filename.endswith('.pdf'):
                    await message.channel.send("📄 *Reading PDF...*")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)
                elif filename.endswith('.docx'):
                    await message.channel.send("📝 *Reading Word Doc...*")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)
        
        # Append document text if any
        if doc_text: user_text += f"\n\n{doc_text}"

        # Check explicit keywords to trigger voice
        if any(word in user_text.lower() for word in ["say", "speak", "tell me", "read", "voice"]):
            should_speak = True

        # 4. SAVE USER MESSAGE TO HISTORY
        new_message_parts = [{"text": user_text}]
        if media_data: new_message_parts.append({"inline_data": media_data})
        add_message_to_history(user_id, "user", new_message_parts)

        # 5. GET AI RESPONSE
        history = get_chat_history(user_id)
        
        async with message.channel.typing():
            response_text = await get_ai_response(history, user_id)
            
            # --- CHECK FOR REMINDERS ---
            # Tag format: [REMIND: time string | task string]
            remind_match = re.search(r'\[REMIND: (.*?) \| (.*?)\]', response_text, re.IGNORECASE)
            if remind_match:
                time_str = remind_match.group(1)
                task_str = remind_match.group(2)
                
                # Parse the time
                real_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
                
                if real_time:
                    add_reminder(user_id, message.channel.id, real_time, task_str)
                    print(f"⏰ Alarm set for: {real_time}")
                    response_text = response_text.replace(remind_match.group(0), f"✅ *Alarm set for {time_str}*")
                else:
                    response_text = response_text.replace(remind_match.group(0), "❌ *I couldn't understand that time.*")

            # Save AI Response to History
            add_message_to_history(user_id, "model", [{"text": response_text}])

            # 6. SEND TEXT REPLY
            # Discord has a 2000 char limit
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 2000):
                    await message.channel.send(response_text[i:i+2000])
            else:
                await message.channel.send(response_text)
            
            # 7. SEND AUDIO REPLY (If enabled)
            if should_speak:
                voice_file = await generate_voice_note(response_text)
                if voice_file:
                    await message.channel.send(file=discord.File(voice_file))
                    cleanup_voice_file(voice_file)

# --- START THE BOT ---
if __name__ == "__main__":
    # Start web server in background thread
    t = threading.Thread(target=run_web_server)
    t.start()
    
    # Start Discord Bot
    client.run(os.getenv("DISCORD_TOKEN"))