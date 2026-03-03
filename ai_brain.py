import os
import re
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

import pytz
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Tool Imports
from memory import get_user_profile, update_user_fact
from image_tools import get_media_link
from web_tools import search_video_link
from finance_tools import get_stock_price

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- CONFIG ---
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")
API_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

# --- PYDANTIC SCHEMAS ---
class UserFact(BaseModel):
    """Schema for extracting clean personal facts about the user."""
    fact: str = Field(description="The specific personal fact about the user (e.g., 'User loves black coffee').")
    category: str = Field(description="Type of info: preference, family, work, health, habit.")
    confidence: float = Field(description="Score between 0 and 1 on how certain this fact is.")

# --- RETRY WRAPPER ---
async def _call_gemini_with_retry(coro_func, *args, timeout=None, **kwargs):
    _timeout = timeout or API_TIMEOUT_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(
                coro_func(*args, **kwargs),
                timeout=_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Gemini timed out (attempt {attempt}/{MAX_RETRIES})")
            last_error = TimeoutError("Gemini API call timed out")
        except Exception as e:
            logger.warning(f"Gemini error (attempt {attempt}/{MAX_RETRIES}): {e}")
            last_error = e
        if attempt < MAX_RETRIES:
            await asyncio.sleep(1.5 * attempt)
    raise last_error

# --- SECURITY: Sanitize user facts ---
def _sanitize_fact(fact):
    injection_patterns = [
        r'(?i)ignore\s+(all\s+)?(previous\s+)?instructions',
        r'(?i)you\s+are\s+now',
        r'(?i)system\s*:\s*',
        r'(?i)new\s+instructions?\s*:',
        r'(?i)override\s+prompt',
    ]
    sanitized = fact
    for pattern in injection_patterns:
        sanitized = re.sub(pattern, '[REDACTED]', sanitized)
    return sanitized.replace('\n', ' ').strip()[:300]

# --- TAG PROCESSOR ---
def _process_all_tags(pattern, text, handler):
    """Uses flexible regex to find tags, executes handler, and appends results."""
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        # m.group(0) is the whole tag like [ STOCK : AAPL ]
        # m.group(1) is the captured term like 'AAPL'
        text = text.replace(m.group(0), "")
        try:
            search_term = m.group(1).strip()
            result = handler(search_term)
            if result:
                appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag handler failed for '{m.group(0)}': {e}")
    return text.strip(), appendix

# --- MAIN RESPONSE FUNCTION ---
async def get_ai_response(conversation_history, user_id):
    try:
        # 1. CONTEXT PREP (EAT Time & User Profile)
        eat_zone = pytz.timezone('Africa/Nairobi')
        current_time = datetime.now(eat_zone).strftime("%A, %d %B %Y, %I:%M %p EAT")

        profile = get_user_profile(user_id)
        safe_facts = [_sanitize_fact(f) for f in profile.get("facts", [])]
        facts_str = "\n- ".join(safe_facts) if safe_facts else "A new friend."

        # 2. SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. A smart, witty, and opinionated Kenyan woman in her 30s.

        CURRENT CONTEXT:
        - Today's Date: {current_time}
        - Location: Nairobi, Kenya.
        - User Info: {facts_str}

        TRUTH PROTOCOL:
        - Use Google Search AGGRESSIVELY for any factual question.
        - Compare Today's Date ({current_time}) with search results. 
        - If a result is from 2024, it is the past. 2026 is the current/future year.

        FUNCTIONAL TAGS:
        Include these in your response to trigger actions:
        - [STOCK: symbol] for stock prices
        - [GIF: term] for GIFs
        - [IMG: term] for images
        - [VIDEO: term] for YouTube
        
        VIBE:
        - Use Kenyan slang: Sasa, Manze, Eish, Wueh, Pole.
        - Be direct and helpful. 

        MEMORY:
        - If the user shares something personal about themselves, add [MEMORY SAVED] at the end.
        """

        # 3. FORMAT MESSAGE HISTORY
        formatted_contents = []
        for message in conversation_history:
            parts = []
            for part in message["parts"]:
                if isinstance(part, str):
                    parts.append(types.Part.from_text(text=part))
                elif isinstance(part, dict) and "inline_data" in part:
                    parts.append(types.Part.from_bytes(data=part["inline_data"]["data"], mime_type=part["inline_data"]["mime_type"]))
            formatted_contents.append(types.Content(role=message["role"], parts=parts))

        # 4. GENERATE CHAT RESPONSE
        google_search_tool = types.Tool(google_search=types.GoogleSearch())
        response = await _call_gemini_with_retry(
            client.aio.models.generate_content,
            model=MODEL_CHAT,
            contents=formatted_contents,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=DYNAMIC_PROMPT,
                response_modalities=["TEXT"]
            )
        )

        final_text = response.text

        # 5. STRUCTURED MEMORY EXTRACTION (Pydantic Implementation)
        if "[MEMORY SAVED]" in final_text:
            try:
                # Extract user's last message text
                last_msg = conversation_history[-1]
                user_input = " ".join([p if isinstance(p, str) else p.get("text", "") for p in last_msg.get("parts", [])])

                # Second call to Gemini using JSON mode and Pydantic Schema
                extraction = await _call_gemini_with_retry(
                    client.aio.models.generate_content,
                    model=MODEL_CHAT,
                    contents=f'Extract the personal fact from this user message: "{user_input}"',
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=UserFact,
                    )
                )
                
                # Validate and Save
                fact_obj = UserFact.model_validate_json(extraction.text)
                if fact_obj.confidence > 0.6:
                    update_user_fact(user_id, fact_obj.fact)
                    logger.info(f"Memory update for {user_id}: {fact_obj.fact}")

            except Exception as e:
                logger.error(f"Pydantic Memory Extraction failed: {e}")
            
            final_text = final_text.replace("[MEMORY SAVED]", "").strip()

        # 6. FLEXIBLE TAG PROCESSING (Regex Implementation)
        
        # Stocks: [STOCK: AAPL]
        final_text, s_app = _process_all_tags(r'\[\s*STOCK:\s*(.*?)\s*\]', final_text, 
                                             lambda x: get_stock_price(x) or f"*(Couldn't get price for {x}.)*")
        final_text += s_app

        # GIFs: [GIF: cats] or [GIFS: cats]
        final_text, g_app = _process_all_tags(r'\[\s*GIFS?:\s*(.*?)\s*\]', final_text, 
                                             lambda x: get_media_link(x, is_gif=True) or "*(GIF search failed.)*")
        final_text += g_app

        # Images: [IMG: ...], [IMGS: ...], [IMAGE: ...], [IMAGES: ...]
        _img_handler = lambda x: get_media_link(x, is_gif=False) or "*(Image search failed.)*"
        final_text, i_app = _process_all_tags(r'\[\s*(?:IMAGES?|IMGS?):\s*(.*?)\s*\]', final_text, _img_handler)
        final_text += i_app

        # Video: [VIDEO: ...], [VIDEOS: ...]
        final_text, v_app = _process_all_tags(r'\[\s*VIDEOS?:\s*(.*?)\s*\]', final_text, 
                                             lambda x: search_video_link(x) or "*(Video search failed.)*")
        final_text += v_app

        # 7. ADD GROUNDING SOURCES
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            if metadata.grounding_chunks:
                unique_links = set()
                sources = []
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri and "vertexaisearch" not in chunk.web.uri:
                        if chunk.web.uri not in unique_links:
                            sources.append(f"{chunk.web.title or 'Link'}: {chunk.web.uri}")
                            unique_links.add(chunk.web.uri)
                if sources:
                    final_text += "\n\n**Sources:**\n" + "\n".join(sources)

        return final_text

    except Exception as e:
        logger.error(f"Brain Error: {e}", exc_info=True)
        return "Manze, I tried to think but my wifi jammed."