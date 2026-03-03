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

# Tool Imports (Ensure these files exist in your folder)
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

# --- PYDANTIC SCHEMA for Memory ---
class UserFact(BaseModel):
    fact: str = Field(description="The specific personal fact about the user.")
    category: str = Field(description="Type: preference, family, work, health.")
    confidence: float = Field(description="Score between 0 and 1.")

# --- KOYEB HEALTH CHECK SERVER ---
# This stops Koyeb from restarting your bot every 2 minutes
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Emily is alive and kicking!")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    logger.info("✅ Health check server started on port 8000")
    server.serve_forever()

# --- HELPER: TAG PROCESSOR ---
def _process_all_tags(pattern, text, handler):
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            result = handler(m.group(1).strip())
            if result: appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag handler failed: {e}")
    return text.strip(), appendix

# --- EMILY'S BRAIN LOGIC ---
async def get_ai_response(conversation_history, user_id):
    try:
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")
        profile = get_user_profile(user_id)
        facts = "\n- ".join([f for f in profile.get("facts", [])])

        DYNAMIC_PROMPT = f"""
        You are Emily. A witty, smart Kenyan woman. 
        Date: {current_time}. Location: Nairobi. User Info: {facts if facts else "A new friend."}
        
        PROTOCOLS:
        - Use Google Search for EVERY factual question (stocks, news, prices).
        - Tags: [STOCK: symbol], [GIF: term], [IMG: term], [VIDEO: term].
        - Slang: Manze, Wueh, Sasa, Pole.
        - If the user shares a fact, end with [MEMORY SAVED].
        """

        # Format history for Gemini
        formatted_contents = []
        for msg in conversation_history:
            parts = [types.Part.from_text(text=p if isinstance(p, str) else p.get("text", "")) for p in msg["parts"]]
            formatted_contents.append(types.Content(role=msg["role"], parts=parts))

        # Call Gemini
        search_tool = types.Tool(google_search=types.GoogleSearch())
        response = await client.aio.models.generate_content(
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(tools=[search_tool], system_instruction=DYNAMIC_PROMPT)
        )
        final_text = response.text

        # 1. Structured Memory Extraction
        if "[MEMORY SAVED]" in final_text:
            try:
                last_user_msg = conversation_history[-1]["parts"][0]["text"]
                extraction = await client.aio.models.generate_content(
                    model=MODEL_CHAT,
                    contents=f'Extract fact from: "{last_user_msg}"',
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=UserFact)
                )
                raw_json = extraction.text.strip()
                if "```" in raw_json:
                    raw_json = re.sub(r'^```(?:json)?\n?|(?:\n?)+```$', '', raw_json, flags=re.MULTILINE).strip()
                
                fact_obj = UserFact.model_validate_json(raw_json)
                if fact_obj.confidence > 0.6:
                    update_user_fact(user_id, fact_obj.fact, fact_obj.category)
            except: pass
            final_text = final_text.replace("[MEMORY SAVED]", "").strip()

        # 2. Process Tags
        final_text, s = _process_all_tags(r'\[\s*STOCK:\s*(.*?)\s*\]', final_text, lambda x: get_stock_price(x))
        final_text += s
        final_text, g = _process_all_tags(r'\[\s*GIFS?:\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=True))
        final_text += g
        final_text, i = _process_all_tags(r'\[\s*(?:IMAGES?|IMGS?):\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=False))
        final_text += i
        
        return final_text
    except Exception as e:
        logger.error(f"Error: {e}")
        return "Manze, my head is heavy. Let's talk later."

# --- DISCORD BOT BODY ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info(f"🚀 Emily is connected to Discord: {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # Respond if tagged or DM'd
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        async with message.channel.typing():
            user_id = str(message.author.id)
            clean_msg = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
            
            # Context and Brain
            history = get_chat_history(user_id)
            history.append({"role": "user", "parts": [{"text": clean_msg}]})
            
            response = await get_ai_response(history, user_id)
            
            # Save and Send
            await message.reply(response)
            add_message_to_history(user_id, "user", [{"text": clean_msg}])
            add_message_to_history(user_id, "model", [{"text": response}])

# --- START EVERYTHING ---
if __name__ == "__main__":
    # 1. Start Health Server in background
    threading.Thread(target=run_health_server, daemon=True).start()
    
    # 2. Start Discord Bot (This keeps the app running forever)
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        logger.error("❌ No DISCORD_TOKEN found!")