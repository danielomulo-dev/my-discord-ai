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
from web_tools import search_video_link
from finance_tools import get_stock_price

# Load environment variables
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
        # Safe access to facts
        user_facts_list = profile.get("facts", [])
        facts = "\n- ".join(user_facts_list)

        DYNAMIC_PROMPT = f"""
        You are Emily. A smart, witty, Kenyan woman (30s).
        CONTEXT: Today is {current_time}. User Info: {facts}.
        
        🚨 **TRUTH PROTOCOL:**
        1. **NO HALLUCINATIONS:** If you don't know, SEARCH.
        2. **NEWS & FACTS:** If asked about news, politics, or events, **USE YOUR GOOGLE SEARCH TOOL**. Do NOT use a tag. Just perform the search internally and summarize the results.
        3. **VERIFY DATES:** If Today is 2026 and search results say "June 2025", that event is in the PAST.

        PRINCIPLES:
        1. **Informed Citizen:** You follow the news. If asked "What's happening in Iran?", SEARCH GOOGLE immediately.
        2. **Honesty:** No hallucinations.
        3. **Ride or Die:** Helpful but opinionated.
        
        CAPABILITIES (Use these tags ONLY for these specific tasks):
        - [STOCK: symbol] -> For live prices (e.g. [STOCK: SCOM]).
        - [GIF: query] / [IMG: query] -> For visuals.
        - [VIDEO: query] -> For YouTube.
        - [REMIND: time | task] -> For Alarms.
        - [RESEARCH: topic] -> For downloadable text reports.
        
        *Note: For general news, do NOT use a tag. Just use your internal Google Search.*
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

        # Enable Native Google Search
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

        # PROCESS TAGS (Note: [NEWS] is removed because we use Native Search now)
        
        # 1. STOCKS
        final_text, s_add = _process_all_tags(r'\[STOCK: (.*?)\]', final_text, lambda x: get_stock_price(x))
        final_text += s_add
        
        # 2. MEDIA
        final_text, g_add = _process_all_tags(r'\[GIFS?: (.*?)\]', final_text, lambda x: get_media_link(x, True))
        final_text += g_add
        
        final_text, i_add = _process_all_tags(r'\[IMGS?: (.*?)\]', final_text, lambda x: get_media_link(x, False))
        final_text += i_add
        
        final_text, v_add = _process_all_tags(r'\[VIDEOS?: (.*?)\]', final_text, lambda x: search_video_link(x))
        final_text += v_add

        # CLEAN LINKS (Standardize Markdown)
        if os.getenv("STRIP_MD_LINKS", "0") == "1":
            final_text = re.sub(r'\[.*?\]\((https?://.*?)\)', r'\1', final_text)

        # GOOGLE SOURCES (This puts the links at the bottom like in your "Good" screenshot)
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            if metadata.grounding_chunks:
                unique_links = set()
                sources_text = "\n\n**Check these out:**"
                has_sources = False
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        url = chunk.web.uri
                        title = chunk.web.title if chunk.web.title else "Link"
                        if url not in unique_links:
                            sources_text += f"\n👉 [{title}]({url})"
                            unique_links.add(url)
                            has_sources = True
                if has_sources:
                    final_text += sources_text

        return final_text

    except Exception as e:
        logger.error(f"Brain Error: {e}")
        return "Manze, I tried to think but my wifi jammed. 😵‍💫"