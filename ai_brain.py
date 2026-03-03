import os
import re
import asyncio
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
from google import genai
from google.genai import types
from memory import get_user_profile, update_user_fact
from image_tools import get_media_link
from web_tools import search_video_link, get_latest_news # <--- NEW IMPORT
from finance_tools import get_stock_price

load_dotenv()
logger = logging.getLogger(__name__)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Configuration
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")

async def _call_gemini_with_retry(coro_func, *args, **kwargs):
    try:
        return await asyncio.wait_for(coro_func(*args, **kwargs), timeout=30)
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        raise e

def _process_all_tags(pattern, text, handler):
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            res = handler(m.group(1))
            if res: appendix += f"\n\n{res}"
        except: pass
    return text.strip(), appendix

async def get_ai_response(conversation_history, user_id):
    try:
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")
        
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile.get("facts", []))

        DYNAMIC_PROMPT = f"""
        You are Emily. A smart, witty, Kenyan woman (30s).
        CONTEXT: Today is {current_time}. User Info: {facts}.
        
        PRINCIPLES:
        1. **News Anchor:** If asked for "latest news", "what's happening in X", or "updates", DO NOT summarize from your memory. USE THE TAG: [NEWS: topic].
           - Example: "What's up in Iran?" -> "Let me pull the headlines. [NEWS: Iran current events]"
        2. **Honesty:** No hallucinations.
        3. **Ride or Die:** Helpful but opinionated.
        
        CAPABILITIES (Use these tags):
        - [NEWS: topic] -> Fetches real headlines.
        - [STOCK: symbol], [GIF: query], [IMG: query], [VIDEO: query]
        - [REMIND: time | task], [RESEARCH: topic]
        """

        formatted_contents = []
        for message in conversation_history:
            parts = []
            for part in message["parts"]:
                if isinstance(part, str): parts.append(types.Part.from_text(text=part))
                elif isinstance(part, dict):
                    if "text" in part: parts.append(types.Part.from_text(text=part["text"]))
                    elif "inline_data" in part: parts.append(types.Part.from_bytes(data=part["inline_data"]["data"], mime_type=part["inline_data"]["mime_type"]))
            if parts: formatted_contents.append(types.Content(role=message["role"], parts=parts))

        google_search = types.Tool(google_search=types.GoogleSearch())
        
        response = await _call_gemini_with_retry(
            client.aio.models.generate_content,
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(tools=[google_search], system_instruction=DYNAMIC_PROMPT, response_modalities=["TEXT"])
        )
        final_text = response.text

        # MEMORY SAVE
        if "[MEMORY SAVED]" in final_text:
            final_text = final_text.replace("[MEMORY SAVED]", "")
            # (Memory saving logic here - simplified for brevity)

        # PROCESS TAGS
        # 1. NEWS (New!)
        final_text, n_add = _process_all_tags(r'\[NEWS: (.*?)\]', final_text, lambda x: get_latest_news(x))
        final_text += n_add

        # 2. STOCKS
        final_text, s_add = _process_all_tags(r'\[STOCK: (.*?)\]', final_text, lambda x: get_stock_price(x))
        final_text += s_add
        
        # 3. MEDIA
        final_text, g_add = _process_all_tags(r'\[GIFS?: (.*?)\]', final_text, lambda x: get_media_link(x, True))
        final_text += g_add
        
        final_text, i_add = _process_all_tags(r'\[IMGS?: (.*?)\]', final_text, lambda x: get_media_link(x, False))
        final_text += i_add
        
        final_text, v_add = _process_all_tags(r'\[VIDEOS?: (.*?)\]', final_text, lambda x: search_video_link(x))
        final_text += v_add

        # CLEAN LINKS
        if os.getenv("STRIP_MD_LINKS", "0") == "1":
            final_text = re.sub(r'\[.*?\]\((https?://.*?)\)', r'\1', final_text)

        return final_text

    except Exception as e:
        logger.error(f"Brain Error: {e}")
        return "Manze, I tried to think but my wifi jammed. 😵‍💫"