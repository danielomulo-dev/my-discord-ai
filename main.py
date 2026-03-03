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

# --- COMMON NAME TO TICKER MAP ---
NAME_TO_TICKER = {
    # NSE Kenya
    "SAFARICOM": "SCOM", "EQUITY": "EQTY", "KCB": "KCB",
    "COOPERATIVE": "COOP", "COOP": "COOP", "ABSA": "ABSA",
    "STANBIC": "SBIC", "NCBA": "NCBA", "DTB": "DTB",
    "DIAMOND TRUST": "DTB", "I&M": "IMH", "IM": "IMH",
    "HF": "HF", "CIC": "CIC", "BRITAM": "BRIT", "JUBILEE": "JUB",
    "LIBERTY": "LKN", "KENYA RE": "KNRE", "KENRE": "KNRE",
    "EABL": "EABL", "BAT": "BAT", "BAMBURI": "BAMB",
    "KENGEN": "KEGN", "KENYA POWER": "KPLC", "KPLC": "KPLC",
    "TOTAL": "TOTAL", "AIRTEL": "AIRTEL", "CENTUM": "CTUM",
    "SASINI": "SASN", "KAKUZI": "KUKZ", "NATION": "NMG",
    "NATION MEDIA": "NMG", "STANDARD GROUP": "SGL",
    # Global
    "MICROSOFT": "MSFT", "APPLE": "AAPL", "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL", "TESLA": "TSLA", "AMAZON": "AMZN",
    "META": "META", "FACEBOOK": "META", "NVIDIA": "NVDA",
    "NETFLIX": "NFLX", "AMD": "AMD", "INTEL": "INTC",
    "BITCOIN": "BTC-USD", "ETHEREUM": "ETH-USD",
}

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

    def do_HEAD(self):
        """Handle HEAD requests (UptimeRobot uses these)."""
        if bot.is_ready():
            self.send_response(200)
        else:
            self.send_response(503)
        self.send_header('Content-type', 'text/plain')
        self.send_header('Connection', 'close')
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_server(ready_event):
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server LIVE on port {port}")
    ready_event.set()
    server.serve_forever()

# --- HELPER: TAG PROCESSOR (async-safe) ---
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

# --- STOCK QUERY DETECTOR ---
def _detect_stock_query(text):
    """
    Detect if the user is asking about a stock and return the ticker.
    Returns ticker string or None.
    """
    text_upper = text.upper()

    # Pattern 1: "price of X", "X stock price", "X shares"
    patterns = [
        r'(?:current\s+)?(?:price|stock|shares?|value)\s+(?:of\s+|for\s+)?["\']?(\w[\w\s&]*\w?)["\']?',
        r'["\']?(\w[\w\s&]*\w?)["\']?\s+(?:stock|shares?|price|current price)',
        r'how\s+(?:is|are|did|has|much)\s+["\']?(\w[\w\s&]*\w?)["\']?\s+(?:stock|shares?|perform|doing|trading|priced)',
        r'how\s+(?:is|are|did|has)\s+["\']?(\w[\w\s&]*\w?)["\']?\s+(?:on\s+(?:the\s+)?(?:nse|market|exchange))',
        r'(?:tell\s+me\s+about|check|get|fetch|look\s+up)\s+["\']?(\w[\w\s&]*\w?)["\']?\s+(?:stock|shares?|price)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).strip().upper()
            # Check name map first
            if raw in NAME_TO_TICKER:
                return NAME_TO_TICKER[raw]
            # Check if it's already a valid ticker (short uppercase)
            if len(raw) <= 6 and raw.isalpha():
                return raw
            # Try each word individually against the name map
            for word in raw.split():
                if word in NAME_TO_TICKER:
                    return NAME_TO_TICKER[word]

    # Pattern 2: Direct ticker mention like "$SCOM" or "$MSFT"
    dollar_match = re.search(r'\$(\w{1,6})', text_upper)
    if dollar_match:
        ticker = dollar_match.group(1)
        return NAME_TO_TICKER.get(ticker, ticker)

    return None

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

        CRITICAL TOOL RULES:
        - When asked about ANY stock price, share performance, or market data, you MUST include [STOCK: SYMBOL] in your response. 
          Example: "Let me check that for you! [STOCK: SCOM]" for Safaricom.
        - NEVER try to answer stock/share prices from your own knowledge or Google Search. ALWAYS use the [STOCK: SYMBOL] tag.
        - Common NSE tickers: SCOM (Safaricom), KCB, EQTY (Equity), COOP, ABSA, EABL, BAT, KPLC (Kenya Power), KEGN (KenGen)
        - For GIFs use [GIF: term], for images use [IMG: term], for videos use [VIDEO: term]

        PERSONALITY:
        - Use Manze, Wueh, Sasa, Pole for flavor.
        - Keep it fun and conversational.
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

        # Tag Logic (async - won't block event loop)
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

            # ─── AUTO-DETECT STOCK QUERIES (bypass Gemini) ───
            detected_ticker = _detect_stock_query(clean_msg)
            if detected_ticker:
                logger.info(f"Stock query detected: {detected_ticker}")
                stock_data = await asyncio.to_thread(get_stock_price, detected_ticker)
                if stock_data and "couldn't find" not in stock_data:
                    # Add some Emily flavor around the raw data
                    flavor_prefix = "Sawa, let me pull that up for you!\n\n"
                    full_response = flavor_prefix + stock_data
                    await send_chunked_reply(message, full_response)
                    add_message_to_history(user_id, "user", [{"text": clean_msg}])
                    add_message_to_history(user_id, "model", [{"text": full_response}])
                    return  # Done — skip Gemini entirely

            # ─── NORMAL AI FLOW ───
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
    health_ready.wait(timeout=10)

    # 2. Start Discord Bot
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        logger.error("No DISCORD_TOKEN found!")
