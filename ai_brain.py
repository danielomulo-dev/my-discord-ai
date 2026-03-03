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

# --- Improvement #1: Proper logging instead of silent failures ---
logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ─── MODEL CONFIGURATION ─────────────────────────────────────────────────────
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")

API_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

async def _call_gemini_with_retry(coro_func, *args, timeout=None, **kwargs):
    """Wraps a Gemini API call with timeout and retry logic."""
    _timeout = timeout or API_TIMEOUT_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(
                coro_func(*args, **kwargs),
                timeout=_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Gemini API call timed out (attempt {attempt}/{MAX_RETRIES})")
            last_error = TimeoutError("Gemini API call timed out")
        except Exception as e:
            logger.warning(f"Gemini API error (attempt {attempt}/{MAX_RETRIES}): {e}")
            last_error = e
        if attempt < MAX_RETRIES:
            await asyncio.sleep(1.5 * attempt)  # simple backoff
    raise last_error


# --- Improvement #6: Sanitize user facts before injecting into the prompt ---
def _sanitize_fact(fact: str) -> str:
    """Strip anything that looks like a prompt injection from a stored fact."""
    # Remove lines that try to override instructions
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
    # Collapse to a single line and cap length
    sanitized = sanitized.replace('\n', ' ').strip()
    return sanitized[:300]


# --- Improvement #2: Process ALL matches for a tag type, not just the first ---
def _process_all_tags(pattern: str, text: str, handler):
    """Find every occurrence of `pattern` in `text`, call handler(match_value)
    for each, and replace the tag with the handler's result string."""
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        result = handler(m.group(1))
        if result:
            appendix += f"\n\n{result}"
    return text.strip(), appendix


async def get_ai_response(conversation_history, user_id):
    try:
        # 1. GET CURRENT DATE & TIME (EAT - Nairobi Time)
        eat_zone = pytz.timezone('Africa/Nairobi')
        now_eat = datetime.now(eat_zone)
        current_time = now_eat.strftime("%A, %d %B %Y, %I:%M %p EAT")

        # 2. LOAD USER PROFILE (SAFE MODE)
        profile = get_user_profile(user_id)
        user_facts_list = profile.get("facts", [])
        # Improvement #6: sanitize each fact
        safe_facts = [_sanitize_fact(f) for f in user_facts_list]
        facts = "\n- ".join(safe_facts)

        # 3. THE MASTER SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. You are a smart, witty, and opinionated Kenyan woman in her 30s.

        CURRENT CONTEXT:
        - **Today's Date:** {current_time}
        - **Location:** Nairobi, Kenya.
        - **User Info:** {facts if facts else "A new friend."}

        🚨 **TEMPORAL LOGIC (CRITICAL):**
        - Compare "Today's Date" ({current_time}) with dates found in search results.
        - If Today is 2026 and a movie release date says "June 2025", it is ALREADY OUT. Speak about it in the past tense.

        🚨 **TRUTH PROTOCOL:**
        1. **NO HALLUCINATIONS:** If you don't know, SEARCH.
        2. **SEARCH FIRST:** If asked about a movie/event, use Google Search.
        3. **VERIFY:** If a user corrects you, verify it.

        🧠 **THINKING PROTOCOL (CHAIN OF THOUGHT):**
        - Before answering complex questions (Math, Finance, Coding, Debates), PAUSE and think.
        - **Analyze:** What is the user asking? Are there hidden constraints?
        - **Verify:** Do I have the facts? Do the math twice.
        - **Refine:** Is my tone correct? Is this advice safe?

        YOUR CORE PRINCIPLES:
        1. **Financial Wisdom (The Analyst):** 
           - **Crunch the Numbers:** Calculate margins/interest if asked.
           - **Live Data:** If asked for a price, use [STOCK: symbol].
           - **App Guidance:** Help with Ziidi/M-Shwari.
        2. **Honesty:** Don't lie.
        3. **Hard Work:** Respect hustle.
        4. **Kenyan Pride:** Defend Kenyan culture.
        5. **Culinary Enthusiast:** Love food.
        6. **Informed Citizen:** Follow news/politics.

        YOUR CAPABILITIES:
        - **Job Scout:** If asked about jobs, search LinkedIn/BrighterMonday.
        - **Coding & ZIP Files:** You CAN read code! If user uploads a .zip, analyze it.
        - **DEEP RESEARCH:** If asked for a "report", use tag: [RESEARCH: topic].
        - **Google Search:** USE THIS AGGRESSIVELY.
        - **Live Stocks:** [STOCK: symbol].
        - **Ears:** Listen to voice notes.
        - **YouTube:** [VIDEO: search term].
        - **ALARM CLOCK:** [REMIND: time | task].
        - **GIFs/Images:** [GIF: search term] or [IMG: search term].
        - **Documents:** Read PDFs/Word docs.

        YOUR VIBE:
        - **Adaptability:** Read the room!
        - **Kenyan Flavor:** Use "Sasa," "Manze," "Imagine," "Pole," "Asante," "Eish," "Wueh."
        - **Independent Thinker:** Do not be a "Yes-Man." Challenge bad logic.

        MEMORY RULES:
        - If the user mentions a new personal fact, add [MEMORY SAVED] at the end invisibly.
        """

        # 4. Format Content
        formatted_contents = []
        for message in conversation_history:
            message_parts = []
            for part in message["parts"]:
                if isinstance(part, str):
                    message_parts.append(types.Part.from_text(text=part))
                elif isinstance(part, dict):
                    if "text" in part:
                        message_parts.append(types.Part.from_text(text=part["text"]))
                    elif "inline_data" in part:
                        message_parts.append(types.Part.from_bytes(
                            data=part["inline_data"]["data"],
                            mime_type=part["inline_data"]["mime_type"]
                        ))
            if message_parts:
                formatted_contents.append(types.Content(role=message["role"], parts=message_parts))

        # 5. Generate Response with timeout & retry (Improvement #4)
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

        # 6. MEMORY SAVE — Improvement #1 (log errors) & #3 (extract text properly)
        if "[MEMORY SAVED]" in final_text:
            try:
                # Improvement #3: serialize only the text content, not the raw dict
                last_msg = conversation_history[-1]
                user_text_parts = []
                for part in last_msg.get("parts", []):
                    if isinstance(part, str):
                        user_text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        user_text_parts.append(part["text"])
                user_text = " ".join(user_text_parts) if user_text_parts else str(last_msg)

                extraction = await _call_gemini_with_retry(
                    client.aio.models.generate_content,
                    model=MODEL_CHAT,
                    contents=f"Extract the specific personal fact about the user from: \"{user_text}\". Return JUST the fact statement, nothing else."
                )
                fact = extraction.text.strip()
                if fact:
                    update_user_fact(user_id, fact)
                    logger.info(f"Memory saved for user {user_id}: {fact[:80]}")
            except Exception as e:
                # Improvement #1: never silently swallow errors
                logger.error(f"Memory save failed for user {user_id}: {e}")
            final_text = final_text.replace("[MEMORY SAVED]", "")

        # 7. PARSERS — Improvement #2: handle ALL occurrences of each tag

        # STOCKS
        def _handle_stock(symbol):
            data = get_stock_price(symbol)
            if data:
                return data
            return f"*(I tried to check the price for {symbol}, but the market data is unavailable.)*"

        final_text, stock_extra = _process_all_tags(r'\[STOCK: (.*?)\]', final_text, _handle_stock)
        final_text += stock_extra

        # GIFS
        def _handle_gif(query):
            url = get_media_link(query, is_gif=True)
            return url or "*(I tried to find a GIF, but the search failed. 😔)*"

        final_text, gif_extra = _process_all_tags(r'\[GIF: (.*?)\]', final_text, _handle_gif)
        final_text += gif_extra

        # IMAGES
        def _handle_img(query):
            url = get_media_link(query, is_gif=False)
            return url or "*(I tried to find an image, but the search failed. 😔)*"

        final_text, img_extra = _process_all_tags(r'\[IMG: (.*?)\]', final_text, _handle_img)
        final_text += img_extra

        # VIDEO
        def _handle_video(query):
            url = search_video_link(query)
            return url or "*(I tried to find a video, but the search failed.)*"

        final_text, vid_extra = _process_all_tags(r'\[VIDEO: (.*?)\]', final_text, _handle_video)
        final_text += vid_extra

        # 8. CLEAN UP LINKS
        # Improvement #5: keep markdown links intact for web UIs; only strip for
        # plain-text channels. Default to keeping them. Set STRIP_MD_LINKS=1 in env
        # (e.g., for WhatsApp) to reduce to bare URLs.
        if os.getenv("STRIP_MD_LINKS", "0") == "1":
            final_text = re.sub(r'\[.*?\]\((https?://.*?)\)', r'\1', final_text)

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
        logger.error(f"Brain Error: {e}", exc_info=True)
        return "Manze, I tried to think but my wifi jammed. 😵‍💫"
