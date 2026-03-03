import os
import re
import asyncio
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Tool Imports
from memory import get_user_profile, update_user_fact, set_voice_mode
from image_tools import get_media_link
from web_tools import search_video_link
from finance_tools import get_stock_price

load_dotenv()
logger = logging.getLogger(__name__)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- CONFIG ---
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")
API_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

# --- PYDANTIC SCHEMA ---
class UserFact(BaseModel):
    fact: str = Field(description="The specific personal fact about the user.")
    category: str = Field(description="Type: preference, family, work, health.")
    confidence: float = Field(description="Score between 0 and 1.")

# --- RETRY WRAPPER ---
async def _call_gemini_with_retry(coro_func, *args, timeout=None, **kwargs):
    _timeout = timeout or API_TIMEOUT_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(coro_func(*args, **kwargs), timeout=_timeout)
        except Exception as e:
            logger.warning(f"Gemini error (attempt {attempt}/{MAX_RETRIES}): {e}")
            last_error = e
        if attempt < MAX_RETRIES:
            await asyncio.sleep(1.5 * attempt)
    raise last_error

# --- SECURITY: Sanitize user facts ---
def _sanitize_fact(fact):
    injection_patterns = [r'(?i)ignore\s+all\s+instructions', r'(?i)system\s*:\s*']
    sanitized = fact
    for pattern in injection_patterns:
        sanitized = re.sub(pattern, '[REDACTED]', sanitized)
    return sanitized.replace('\n', ' ').strip()[:300]

# --- TAG PROCESSOR ---
def _process_all_tags(pattern, text, handler):
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            result = handler(m.group(1).strip())
            if result: appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag handler failed for '{m.group(0)}': {e}")
    return text.strip(), appendix

# --- MAIN RESPONSE LOGIC ---
async def get_ai_response(conversation_history, user_id):
    try:
        # 1. CONTEXT
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")
        profile = get_user_profile(user_id)
        facts = "\n- ".join([_sanitize_fact(f) for f in profile.get("facts", [])])

        # 2. PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. A witty Kenyan woman. 
        Date: {current_time}. Location: Nairobi. User Info: {facts if facts else "New friend."}
        
        PROTOCOLS:
        - Search Google for EVERY factual question (prices, news, people).
        - Tags: [STOCK: symbol], [GIF: term], [IMG: term], [VIDEO: term].
        - Use Kenyan slang (Manze, Wueh, Sasa).
        - If the user shares personal info, end with [MEMORY SAVED].
        """

        # 3. FORMAT HISTORY
        formatted_contents = []
        for msg in conversation_history:
            parts = [types.Part.from_text(text=p) if isinstance(p, str) else types.Part.from_text(text=p.get("text", "")) for p in msg["parts"]]
            formatted_contents.append(types.Content(role=msg["role"], parts=parts))

        # 4. GENERATE RESPONSE
        search_tool = types.Tool(google_search=types.GoogleSearch())
        response = await _call_gemini_with_retry(
            client.aio.models.generate_content,
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(tools=[search_tool], system_instruction=DYNAMIC_PROMPT)
        )
        final_text = response.text

        # 5. STRUCTURED MEMORY EXTRACTION (SAFE)
        if "[MEMORY SAVED]" in final_text:
            try:
                last_msg = conversation_history[-1]
                user_text = " ".join([p if isinstance(p, str) else p.get("text", "") for p in last_msg.get("parts", [])])
                
                extraction = await _call_gemini_with_retry(
                    client.aio.models.generate_content,
                    model=MODEL_CHAT,
                    contents=f'Extract fact from: "{user_text}"',
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=UserFact)
                )
                
                raw_json = extraction.text.strip()
                if "```" in raw_json: # Clean markdown backticks
                    raw_json = re.sub(r'^```(?:json)?\n?|(?:\n?)+```$', '', raw_json, flags=re.MULTILINE).strip()
                
                fact_obj = UserFact.model_validate_json(raw_json)
                if fact_obj.confidence > 0.6:
                    update_user_fact(user_id, fact_obj.fact, fact_obj.category)
            except Exception as e:
                logger.error(f"Memory extraction failed: {e}")
            final_text = final_text.replace("[MEMORY SAVED]", "").strip()

        # 6. TAG PROCESSING
        final_text, s = _process_all_tags(r'\[\s*STOCK:\s*(.*?)\s*\]', final_text, lambda x: get_stock_price(x) or f"*(Couldn't get price for {x}.)*")
        final_text += s
        final_text, g = _process_all_tags(r'\[\s*GIFS?:\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=True) or "*(GIF failed.)*")
        final_text += g
        final_text, i = _process_all_tags(r'\[\s*(?:IMAGES?|IMGS?):\s*(.*?)\s*\]', final_text, lambda x: get_media_link(x, is_gif=False) or "*(Image failed.)*")
        final_text += i
        final_text, v = _process_all_tags(r'\[\s*VIDEOS?:\s*(.*?)\s*\]', final_text, lambda x: search_video_link(x) or "*(Video failed.)*")
        final_text += v

        # 7. GROUNDING SOURCES (SAFE)
        try:
            if response.candidates and response.candidates[0].grounding_metadata:
                metadata = response.candidates[0].grounding_metadata
                if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    unique_links = set()
                    links_text = "\n\n**Sources:**"
                    has_links = False
                    for chunk in metadata.grounding_chunks:
                        if chunk.web and chunk.web.uri and "vertexaisearch" not in chunk.web.uri:
                            if chunk.web.uri not in unique_links:
                                links_text += f"\n- {chunk.web.title or 'Link'}: {chunk.web.uri}"
                                unique_links.add(chunk.web.uri)
                                has_links = True
                    if has_links: final_text += links_text
        except: pass # Don't crash if sources fail

        return final_text

    except Exception as e:
        logger.error(f"Brain Error: {e}", exc_info=True)
        return "Manze, I tried to think but my wifi jammed."

if __name__ == "__main__":
    logger.info("Starting Emily...")
    t = threading.Thread(target=run_web_server, daemon=True)  # daemon=True for clean shutdown
    t.start()
    try:
        client.run(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        logger.critical(f"Discord connection failed: {e}")
