import os
import re
import asyncio
import logging
import threading
import time
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

# Tool Imports - Ensure these files (memory.py, etc.) are in your folder
from memory import (
    get_user_profile, 
    update_user_fact, 
    set_voice_mode, 
    add_message_to_history, 
    get_chat_history
)
from image_tools import get_media_link
from web_tools import search_video_link
from finance_tools import get_stock_price

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INITIALIZE GEMINI ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")

# --- PYDANTIC SCHEMA for Memory ---
class UserFact(BaseModel):
    fact: str = Field(description="The specific personal fact about the user.")
    category: str = Field(description="Type: preference, family, work, health, habit.")
    confidence: float = Field(description="Score between 0 and 1.")

# --- ROBUST HEALTH CHECK SERVER (For Uptime Robot & Koyeb) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Respond to any path with 200 OK and a simple "OK" body
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(b"OK - Emily is active")

    def log_message(self, format, *args):
        return # Keep logs clean from health pings

def run_health_server():
    # Bind to PORT provided by Koyeb or default to 8000
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"✅ Health check server LIVE on port {port}")
    server.serve_forever()

# --- HELPER: TAG PROCESSOR ---
def _process_all_tags(pattern, text, handler):
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            search_term = m.group(1).strip()
            result = handler(search_term)
            if result: 
                appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag processor error: {e}")
    return text.strip(), appendix

# --- EMILY'S BRAIN LOGIC ---
async def get_ai_response(conversation_history, user_id):
    try:
        # 1. SETUP CONTEXT
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile.get("facts", []))

        # UPDATED PROMPT: Specific help for Kenyan Stocks (NSE)
        DYNAMIC_PROMPT = f"""
        You are Emily. A smart, witty Kenyan woman in her 30s. 
        Current Time: {current_time}. Location: Nairobi. 
        User Knowledge: {facts if facts else "A new friend."}
        
        FINANCIAL RESEARCH PROTOCOL (CRITICAL):
        - For Kenyan Stocks (Safaricom, KCB, etc.): Search specifically for "NSE Kenya [Company] performance 2024".
        - Use local sources like MyStocks.co.ke or Business Daily for accurate NSE data.
        - For Current Prices, use the tag: [STOCK: ticker]. For Safaricom use [STOCK: SCOM].
        
        CORE PROTOCOLS:
        - Use Google Search AGGRESSIVELY for any news, tech, or stock question.
        - Tags: [STOCK: symbol], [GIF: term], [IMG: term], [VIDEO: term].
        - Use Kenyan Slang: Manze, Wueh, Sasa, Pole, Eish, Yani.
        - If the user shares personal info, end your response with [MEMORY SAVED].
        """

        # Format history for Gemini SDK
        formatted_contents = []
        for msg in conversation_history:
            parts = [types.Part.from_text(text=p if isinstance(p, str) else p.get("text", "")) for p in msg["parts"]]
            formatted_contents.append(types.Content(role=msg["role"], parts=parts))

        # 2. GENERATE RESPONSE
        search_tool = types.Tool(google_search=types.GoogleSearch())
        response = await client.aio.models.generate_content(
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(tools=[search_tool], system_instruction=DYNAMIC_PROMPT)
        )
        final_text = response.text

        # 3. STRUCTURED MEMORY EXTRACTION
        if "[MEMORY SAVED]" in final_text:
            try:
                last_user_msg = conversation_history[-1]["parts"][0]["text"]
                extraction = await client.aio.models.generate_content(
                    model=MODEL_CHAT,
                    contents=f'Extract fact from: "{last_user_msg}"',
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=UserFact)
                )
                raw_json = extraction.text.strip()
                if "```" in raw_json: # Cleanup markdown
                    raw_json = re.sub(r'^```(?:json)?\n?|(?:\n?)+```$', '', raw_json, flags=re.MULTILINE).strip()
                
                fact_obj = UserFact.model_validate_json(raw_json)
                if fact_obj.confidence > 0.6:
                    update_user_fact(user_id, fact_obj.fact, fact_obj.category)
            except Exception as e:
                logger.error(f"Memory extraction failed: {e}")
            final_text = final_text.replace("[MEMORY SAVED]", "").strip()

        # 4. PROCESS MEDIA TAGS
        final_text, s = _process_all_tags(r'\[\s*STOCK:\s*(.*?)\s*\]', final_text, lambda x: get_stock_price(x))
        final_text += s
        final_text, g = _process_all_tags(r'\[\s*GIFS?:\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=True))
        final_text += g
        final_text, i = _process_all_tags(r'\[\s*(?:IMAGES?|IMGS?):\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=False))
        final_text += i
        final_text, v = _process_all_tags(r'\[\s*VIDEOS?:\s*(.*?)\s*\]', final_text, lambda x: search_video_link(x))
        final_text += v
        
        return final_text
    except Exception as e:
        logger.error(f"Major Brain Error: {e}", exc_info=True)
        return "Manze, I tried to think but my wifi jammed. Let's try again?"

# --- DISCORD BOT BODY ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info(f"🚀 Emily connected to Discord: {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # Check for DM or Mention
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        try:
            async with message.channel.typing():
                user_id = str(message.author.id)
                clean_msg = re.sub(r'<@!?\d+>', '', message.content).strip()
                
                # Fetch memory & get response
                history = get_chat_history(user_id)
                history.append({"role": "user", "parts": [{"text": clean_msg}]})
                
                response = await get_ai_response(history, user_id)
                
                # Send response and save to history
                await message.reply(response)
                add_message_to_history(user_id, "user", [{"text": clean_msg}])
                add_message_to_history(user_id, "model", [{"text": response}])
        except Exception as e:
            logger.error(f"Discord Message Error: {e}")
            await message.reply("Eish, something went wrong on my end. Give me a second?")

# --- MAIN STARTUP ---
if __name__ == "__main__":
    # 1. Start Health Thread immediately (Port logic included)
    threading.Thread(target=run_health_server, daemon=True).start()
    
    # 2. Wait a second for server to bind
    time.sleep(1)
    
    # 3. Start Discord Bot (Main Thread - Keeps app alive)
    token = os.getenv("DISCORD_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            logger.error(f"Discord failed to start: {e}")
    else:
        logger.error("❌ CRITICAL: No DISCORD_TOKEN found!")