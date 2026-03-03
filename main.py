import os
import re
import asyncio
import logging
import tempfile
import threading
from datetime import datetime
import dateparser
import pytz
from flask import Flask
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# --- CUSTOM TOOLS IMPORTS ---
from ai_brain import get_ai_response          # ← matches your ai_brain.py
from web_tools import extract_text_from_url
from file_tools import extract_text_from_pdf, extract_text_from_docx, extract_code_from_zip
from researcher import perform_deep_research   # ← matches your researcher.py
from memory import (
    add_message_to_history,
    get_chat_history,
    add_reminder,
    get_due_reminders,
    delete_reminder,
    get_user_profile,
    set_voice_mode,
)
from voice_tools import generate_voice_note, cleanup_voice_file

load_dotenv()

# ─── LOGGING (replaces all print statements) ─────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
URL_PATTERN = r'(https?://\S+)'
DISCORD_MSG_LIMIT = 2000
VOICE_KEYWORDS = re.compile(r'\b(say it|speak|read aloud|voice reply|send voice)\b', re.IGNORECASE)

# --- WEB SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Emily is Online! (Multi-User Support Active)"
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user}')
    if not check_reminders_loop.is_running():
        check_reminders_loop.start()

# --- BACKGROUND TASK ---
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
        logger.error(f"Reminder loop error: {e}")


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _smart_split(text: str, limit: int = DISCORD_MSG_LIMIT) -> list[str]:
    """Split text into chunks that respect Discord's char limit.
    Breaks at paragraphs → newlines → sentences → spaces — never mid-word."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        slice_ = text[:limit]
        # Best break: paragraph
        idx = slice_.rfind("\n\n")
        if idx == -1:
            idx = slice_.rfind("\n")
        if idx == -1:
            idx = max(slice_.rfind(". "), slice_.rfind("? "), slice_.rfind("! "))
        if idx == -1:
            idx = slice_.rfind(" ")
        if idx == -1:
            idx = limit - 1  # hard cut as last resort

        chunks.append(text[:idx + 1])
        text = text[idx + 1:].lstrip()

    return chunks


async def _send_long(channel, text: str):
    """Send a message, splitting smartly if it exceeds Discord's limit."""
    for chunk in _smart_split(text):
        if chunk.strip():
            await channel.send(chunk)


def _clean_for_discord(text: str) -> str:
    """Clean AI response for Discord display.
    
    - Strips markdown links [title](url) → bare URL (Discord auto-embeds bare URLs
      into nice preview cards, but renders markdown links as ugly literal text)
    - Removes Google Vertex redirect URLs (unreadable garbage links)
    - Deduplicates source links
    """
    # 1. Remove vertex redirect URLs entirely (they're unreadable and useless to users)
    text = re.sub(
        r'👉\s*\[.*?\]\(https://vertexaisearch\.cloud\.google\.com/.*?\)\n?',
        '', text
    )
    text = re.sub(
        r'https://vertexaisearch\.cloud\.google\.com/\S+',
        '', text
    )

    # 2. Strip remaining markdown links to bare URLs (Discord auto-previews these)
    text = re.sub(r'\[([^\]]*)\]\((https?://\S+?)\)', r'\2', text)

    # 3. Clean up any leftover empty source sections
    text = re.sub(r'\*\*Check these out:\*\*\s*\n*$', '', text.strip())
    
    # 4. Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# --- MAIN MESSAGE HANDLER ---
@client.event
async def on_message(message):
    if message.author == client.user: return

    # --- COMMANDS ---
    content_lower = message.content.lower().strip()

    if content_lower == "!voice on":
        set_voice_mode(message.author.id, True)
        await message.channel.send("🎙️ **Voice Mode Activated!**")
        return
    if content_lower == "!voice off":
        set_voice_mode(message.author.id, False)
        await message.channel.send("📝 **Voice Mode Deactivated.**")
        return

    # --- CONVERSATION ---
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        
        user_id = message.author.id
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        # 1. CHECK FOR REPLIED MESSAGE (Context Awareness)
        if message.reference:
            try:
                original_msg = await message.channel.fetch_message(message.reference.message_id)
                if original_msg.content:
                    author_name = original_msg.author.display_name
                    user_text = (
                        f'[CONTEXT: Replying to {author_name}: "{original_msg.content}"]\n\n'
                        f"My reply: {user_text}"
                    )
            except Exception as e:
                logger.warning(f"Could not fetch replied message: {e}")

        # 2. PREFERENCE
        profile = get_user_profile(user_id)
        should_speak = profile.get("voice_mode", False) 

        # 3. LINKS — scrape ALL links (capped at 3)
        urls = re.findall(URL_PATTERN, user_text)
        if urls:
            await message.channel.send(f"👀 *Checking {len(urls)} link{'s' if len(urls) > 1 else ''}...*")
            for url in urls[:3]:
                try:
                    scraped = extract_text_from_url(url)
                    if scraped and len(scraped.strip()) > 50:
                        user_text += f"\n\n--- CONTENT FROM {url} ---\n{scraped[:15000]}"
                except Exception as e:
                    logger.warning(f"Failed to scrape {url}: {e}")

        # 4. ATTACHMENTS
        media_data = None
        doc_text = ""

        for attachment in message.attachments:
            filename = attachment.filename.lower()
            try:
                if filename.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    image_bytes = await attachment.read()
                    media_data = {"mime_type": attachment.content_type, "data": image_bytes}
                elif filename.endswith(('.ogg', '.mp3', '.wav', '.m4a')):
                    await message.channel.send("👂 *Listening...*")
                    audio_bytes = await attachment.read()
                    media_data = {"mime_type": attachment.content_type or "audio/ogg", "data": audio_bytes}
                    should_speak = True 
                elif filename.endswith('.pdf'):
                    await message.channel.send("📄 *Reading PDF...*")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_pdf(file_bytes)
                elif filename.endswith('.docx'):
                    await message.channel.send("📝 *Reading Word Doc...*")
                    file_bytes = await attachment.read()
                    doc_text += extract_text_from_docx(file_bytes)
                elif filename.endswith('.zip'):
                    await message.channel.send("📦 *Unzipping code...*")
                    file_bytes = await attachment.read()
                    doc_text += extract_code_from_zip(file_bytes)
            except Exception as e:
                logger.error(f"Failed to process attachment {attachment.filename}: {e}")
                await message.channel.send(f"⚠️ *Couldn't read {attachment.filename}.*")
        
        if doc_text: user_text += f"\n\n{doc_text}"
        
        # Smarter voice trigger — whole phrases only, not bare "say" or "read"
        if VOICE_KEYWORDS.search(user_text):
            should_speak = True

        # 5. SAVE HISTORY & RESPOND
        new_message_parts = [{"text": user_text}]
        if media_data: new_message_parts.append({"inline_data": media_data})
        add_message_to_history(user_id, "user", new_message_parts)

        history = get_chat_history(user_id)
        
        async with message.channel.typing():
            response_text = await get_ai_response(history, user_id)
            
            # 6. RESEARCH — handle ALL matches, safe temp files
            research_matches = list(re.finditer(r'\[RESEARCH: (.*?)\]', response_text, re.IGNORECASE))
            for match in research_matches:
                topic = match.group(1)
                response_text = response_text.replace(match.group(0), "").strip()
                await message.channel.send(f"🕵️‍♀️ *Starting deep research on: {topic}...*")
                try:
                    report = await perform_deep_research(topic)
                    safe_name = re.sub(r'[^\w\s-]', '', topic)[:20].strip().replace(' ', '_')
                    tmp = tempfile.NamedTemporaryFile(
                        prefix=f"Report_{safe_name}_",
                        suffix=".txt",
                        delete=False,
                        mode="w",
                        encoding="utf-8",
                    )
                    tmp.write(report)
                    tmp.close()
                    await message.channel.send("✅ **Research Complete!**", file=discord.File(tmp.name))
                    os.remove(tmp.name)
                    response_text += "\n✅ *Report attached above.*"
                except Exception as e:
                    logger.error(f"Research failed for '{topic}': {e}")
                    response_text += f"\n⚠️ *Research on '{topic}' failed.*"

            # 7. REMINDERS — handle ALL matches
            remind_matches = list(re.finditer(r'\[REMIND: (.*?) \| (.*?)\]', response_text, re.IGNORECASE))
            for match in remind_matches:
                time_str = match.group(1)
                task_str = match.group(2)
                response_text = response_text.replace(match.group(0), "").strip()
                real_time = dateparser.parse(time_str, settings={
                    'PREFER_DATES_FROM': 'future',
                    'TIMEZONE': 'Africa/Nairobi',
                    'TO_TIMEZONE': 'Africa/Nairobi'
                })
                if real_time:
                    add_reminder(user_id, message.channel.id, real_time, task_str)
                    response_text += f"\n✅ *Alarm set for {time_str}.*"
                else:
                    response_text += f"\n❌ *Couldn't parse time: '{time_str}'.*"

            # 8. SAVE & SEND
            add_message_to_history(user_id, "model", [{"text": response_text}])

            # Clean up links for Discord (strip markdown, remove vertex redirects)
            discord_text = _clean_for_discord(response_text)

            if discord_text.strip():
                await _send_long(message.channel, discord_text)
            
            # 9. VOICE NOTE
            if should_speak:
                try:
                    voice_file = await generate_voice_note(response_text)
                    if voice_file:
                        await message.channel.send(file=discord.File(voice_file))
                        cleanup_voice_file(voice_file)
                except Exception as e:
                    logger.error(f"Voice generation failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Emily...")
    t = threading.Thread(target=run_web_server, daemon=True)  # daemon=True for clean shutdown
    t.start()
    try:
        client.run(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        logger.critical(f"Discord connection failed: {e}")
