import os
import re
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import pytz
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Discord & Gemini Imports
import discord
from discord.ext import commands
from google import genai
from google.genai import types

# Tool Imports
from memory import get_user_profile, update_user_fact, set_voice_mode, add_message_to_history, get_chat_history
from image_tools import get_media_link
from web_tools import search_video_link
from finance_tools import get_stock_price

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INITIALIZE GEMINI ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")

# --- CHAT HISTORY LIMIT ---
MAX_HISTORY_MESSAGES = 30

# --- PYDANTIC SCHEMA for Memory ---
class UserFact(BaseModel):
    fact: str = Field(description="The specific personal fact about the user.")
    category: str = Field(description="Type: preference, family, work, health.")
    confidence: float = Field(description="Score between 0 and 1.")

# --- ROBUST HEALTH CHECK SERVER (tied to bot status) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if bot.is_ready():
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(503)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b"Bot not ready")

    def log_message(self, format, *args):
        return  # Quiet logs

def run_health_server(ready_event):
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server LIVE on port {port}")
    ready_event.set()  # Signal that server is bound and ready
    server.serve_forever()

# --- HELPER: TAG PROCESSOR (async-safe, no longer blocks event loop) ---
async def _process_all_tags(pattern, text, handler):
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            search_term = m.group(1).strip()
            result = await asyncio.to_thread(handler, search_term)
            if result:
                appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag error for '{m.group(0)}': {e}")
    return text.strip(), appendix

# --- HELPER: CHUNK MESSAGE FOR DISCORD 2000 CHAR LIMIT ---
async def send_chunked_reply(message, response):
    if not response:
        await message.reply("Manze, I got nothing. Try again?")
        return

    chunks = []
    while len(response) > 2000:
        # Try to split at a newline or space near the limit
        split_at = response.rfind('\n', 0, 2000)
        if split_at == -1:
            split_at = response.rfind(' ', 0, 2000)
        if split_at == -1:
            split_at = 2000
        chunks.append(response[:split_at])
        response = response[split_at:].lstrip()
    if response:
        chunks.append(response)

    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(chunk)
        else:
            await message.channel.send(chunk)

# --- EMILY'S BRAIN ---
async def get_ai_response(conversation_history, user_id):
    try:
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile.get("facts", []))

        DYNAMIC_PROMPT = f"""
        You are Emily. Witty Kenyan woman. 
        Time: {current_time}. Nairobi. History: {facts if facts else "New friend."}
        - Use Google Search for facts/stocks.
        - Tags: [STOCK: symbol], [GIF: term], [IMG: term], [VIDEO: term].
        - Use Manze, Wueh, Sasa.
        - Mention [MEMORY SAVED] if user shares personal info.
        """

        # Trim history to prevent context window overflow
        trimmed_history = conversation_history[-MAX_HISTORY_MESSAGES:]

        formatted_contents = []
        for msg in trimmed_history:
            parts = []
            for p in msg.get("parts", []):
                if isinstance(p, str):
                    parts.append(types.Part.from_text(text=p))
                elif isinstance(p, dict) and "text" in p:
                    parts.append(types.Part.from_text(text=p["text"]))
                else:
                    logger.warning(f"Skipping unrecognized part format: {type(p)}")
                    continue
            if parts:
                formatted_contents.append(types.Content(role=msg["role"], parts=parts))

        search_tool = types.Tool(google_search=types.GoogleSearch())
        response = await client.aio.models.generate_content(
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(tools=[search_tool], system_instruction=DYNAMIC_PROMPT)
        )
        final_text = response.text

        # Memory Logic
        if "[MEMORY SAVED]" in final_text:
            try:
                last_msg = conversation_history[-1]["parts"][0]
                last_text = last_msg if isinstance(last_msg, str) else last_msg.get("text", "")
                extraction = await client.aio.models.generate_content(
                    model=MODEL_CHAT,
                    contents=f'Extract fact from: "{last_text}"',
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=UserFact)
                )
                raw_json = extraction.text.strip()
                if "```" in raw_json:
                    raw_json = re.sub(r'^```(?:json)?\n?|(?:\n?)+```$', '', raw_json, flags=re.MULTILINE).strip()
                fact_obj = UserFact.model_validate_json(raw_json)
                if fact_obj.confidence > 0.6:
                    update_user_fact(user_id, fact_obj.fact, fact_obj.category)
            except Exception as e:
                logger.error(f"Memory extraction failed: {e}")
            final_text = final_text.replace("[MEMORY SAVED]", "").strip()

        # Tag Logic (now async - won't block the event loop)
        final_text, s = await _process_all_tags(r'\[\s*STOCK:\s*(.*?)\s*\]', final_text, lambda x: get_stock_price(x))
        final_text += s
        final_text, g = await _process_all_tags(r'\[\s*GIFS?:\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=True))
        final_text += g
        final_text, i = await _process_all_tags(r'\[\s*(?:IMAGES?|IMGS?):\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=False))
        final_text += i
        final_text, v = await _process_all_tags(r'\[\s*VIDEOS?:\s*(.*?)\s*\]', final_text, lambda x: search_video_link(x))
        final_text += v

        return final_text
    except Exception as e:
        logger.error(f"AI response error: {e}")
        return "Manze, my head is heavy. Try again?"

# --- DISCORD BODY ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Emily connected to Discord: {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        async with message.channel.typing():
            user_id = str(message.author.id)
            clean_msg = re.sub(r'<@!?\d+>', '', message.content).strip()
            if not clean_msg:
                await message.reply("Sasa! You pinged me but said nothing")
                return

            history = get_chat_history(user_id)
            history.append({"role": "user", "parts": [{"text": clean_msg}]})

            response = await get_ai_response(history, user_id)
            await send_chunked_reply(message, response)

            add_message_to_history(user_id, "user", [{"text": clean_msg}])
            add_message_to_history(user_id, "model", [{"text": response}])

# --- START UP ---
if __name__ == "__main__":
    # 1. Start Health Thread with ready signal
    health_ready = threading.Event()
    threading.Thread(target=run_health_server, args=(health_ready,), daemon=True).start()
    health_ready.wait(timeout=10)  # Wait for server to actually bind

    # 2. Start Discord Bot
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        logger.error("No DISCORD_TOKEN found!")