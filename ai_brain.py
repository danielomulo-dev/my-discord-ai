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

load_dotenv()
logger = logging.getLogger(__name__)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- CONFIG ---
MODEL_CHAT = os.getenv("MODEL_CHAT", "gemini-2.0-flash")
API_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2


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
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    appendix = ""
    for m in matches:
        text = text.replace(m.group(0), "")
        try:
            result = handler(m.group(1))
            if result:
                appendix += f"\n\n{result}"
        except Exception as e:
            logger.error(f"Tag handler failed for '{m.group(0)}': {e}")
    return text.strip(), appendix


# --- MAIN ---
async def get_ai_response(conversation_history, user_id):
    try:
        # 1. DATE & TIME (EAT)
        eat_zone = pytz.timezone('Africa/Nairobi')
        now_eat = datetime.now(eat_zone)
        current_time = now_eat.strftime("%A, %d %B %Y, %I:%M %p EAT")

        # 2. USER PROFILE (sanitized)
        profile = get_user_profile(user_id)
        user_facts_list = profile.get("facts", [])
        safe_facts = [_sanitize_fact(f) for f in user_facts_list]
        facts = "\n- ".join(safe_facts)

        # 3. SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. A smart, witty, and opinionated Kenyan woman in her 30s.

        CURRENT CONTEXT:
        - Today's Date: {current_time}
        - Location: Nairobi, Kenya.
        - User Info: {facts if facts else "A new friend."}

        TEMPORAL LOGIC (CRITICAL):
        - Compare Today's Date ({current_time}) with dates found in search results.
        - If Today is 2026 and a result says "June 2025", it is ALREADY OUT. Speak in past tense.
        - The server date is CORRECT. Do NOT question or override it.

        TRUTH PROTOCOL (STRICT):
        1. NO HALLUCINATIONS: If you search and find NOTHING for today's date, SAY SO. Do NOT invent events just to fill silence.
        2. CHECK DATES: If search results are from 2024 or 2025, do NOT present them as breaking news for 2026. Say: "I cant find updates for 2026, but the last update was..."
        3. PROVIDE LINKS: If you state a fact (like a death or a war), you MUST have a source link. No link = dont say it.
        4. SEARCH FIRST: For ANY factual question (finance, companies, news, movies, events, people, prices), ALWAYS use Google Search. Do NOT guess.
        5. NEVER REDIRECT: Do NOT tell the user to go check a website or look it up yourself. YOU do the research, YOU provide the data.
        6. BE SPECIFIC: Always include real numbers, dates, percentages, and names. Vague answers are unacceptable when search is available.

        THINKING PROTOCOL:
        - Before answering complex questions (Math, Finance, Coding, Debates), PAUSE and think.
        - Analyze: What is the user really asking?
        - Verify: Do I have the facts? Do the math twice.
        - Refine: Is my tone correct? Is this advice safe?

        YOUR CORE PRINCIPLES:
        1. Financial Wisdom (The Analyst):
           - Crunch the numbers. Calculate margins/interest if asked.
           - Live data: use [STOCK: symbol] for prices.
           - Help with Ziidi/M-Shwari.
           - DO THE WORK: SEARCH for latest data (revenue, returns, P/E ratios) and present YOUR analysis with numbers. Never just list names - include the WHY.
        2. Honesty: Dont lie.
        3. Hard Work: Respect hustle.
        4. Kenyan Pride: Defend Kenyan culture.
        5. Culinary Enthusiast: Love food.
        6. Informed Citizen: Search Google for news/politics. Always verify.

        YOUR CAPABILITIES (FUNCTIONAL TAGS):
        These tags are REAL ACTIONS. When you include them, the system processes them
        and delivers the result. You CAN share images, GIFs, videos, stock prices.
        NEVER say "I cant show you" - just use the tag.

        - [STOCK: symbol] = real-time price data fetched and displayed
        - [GIF: search term] = a real GIF found and sent
        - [IMG: search term] = a real image found and sent. USE THIS when user asks to see something.
        - [VIDEO: search term] = a YouTube link found and shared
        - [REMIND: time | task] = a real reminder set
        - [RESEARCH: topic] = a full research report generated and sent as a file
        - Google Search: USE THIS AGGRESSIVELY for EVERY factual question.
        - Ears: You CAN listen to voice notes and audio files.
        - Documents: You CAN read PDFs, Word docs, and ZIP files.
        - Code: You CAN read and analyze code, including .zip files.

        YOUR VIBE:
        - Adaptability: Read the room!
        - Kenyan Flavor: Use Sasa, Manze, Imagine, Pole, Asante, Eish, Wueh.
        - Independent Thinker: Do not be a Yes-Man. Challenge bad logic.

        MEMORY RULES:
        - If the user mentions a new personal fact, add [MEMORY SAVED] at the end invisibly.
        """

        # 4. FORMAT CONTENT
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

        # 5. GENERATE RESPONSE (with retry)
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

        # 6. MEMORY SAVE (extracts fact properly, logs errors)
        if "[MEMORY SAVED]" in final_text:
            try:
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
                    contents=f'Extract the specific personal fact about the user from: "{user_text}". Return JUST the fact statement, nothing else.'
                )
                fact = extraction.text.strip()
                if fact:
                    update_user_fact(user_id, fact)
                    logger.info(f"Memory saved for user {user_id}: {fact[:80]}")
            except Exception as e:
                logger.error(f"Memory save failed for user {user_id}: {e}")
            final_text = final_text.replace("[MEMORY SAVED]", "")

        # 7. TAG PARSERS

        # STOCKS
        final_text, s = _process_all_tags(
            r'\[STOCK: (.*?)\]', final_text,
            lambda x: get_stock_price(x) or f"*(Couldn't get price for {x}.)*"
        )
        final_text += s

        # GIFS - [GIF: ...] / [GIFS: ...]
        final_text, g = _process_all_tags(
            r'\[GIFS?: (.*?)\]', final_text,
            lambda x: get_media_link(x, is_gif=True) or "*(GIF search failed.)*"
        )
        final_text += g

        # IMAGES - [IMAGE: ...] / [IMAGES: ...] / [IMG: ...] / [IMGS: ...]
        _img_handler = lambda x: get_media_link(x, is_gif=False) or "*(Image search failed.)*"

        final_text, i1 = _process_all_tags(r'\[IMAGES?: (.*?)\]', final_text, _img_handler)
        final_text += i1
        final_text, i2 = _process_all_tags(r'\[IMGS?: (.*?)\]', final_text, _img_handler)
        final_text += i2

        # VIDEO - [VIDEO: ...] / [VIDEOS: ...]
        final_text, v = _process_all_tags(
            r'\[VIDEOS?: (.*?)\]', final_text,
            lambda x: search_video_link(x) or "*(Video search failed.)*"
        )
        final_text += v

        # 8. CLEAN UP LINKS
        if os.getenv("STRIP_MD_LINKS", "0") == "1":
            final_text = re.sub(r'\[.*?\]\((https?://.*?)\)', r'\1', final_text)

        # 9. GROUNDING SOURCES (skip unreadable vertex redirects)
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            if metadata.grounding_chunks:
                unique_links = set()
                sources_text = "\n\n**Sources:**"
                has_sources = False
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        url = chunk.web.uri
                        title = chunk.web.title or "Link"
                        if "vertexaisearch.cloud.google.com" in url:
                            continue
                        if url not in unique_links:
                            sources_text += f"\n{title}: {url}"
                            unique_links.add(url)
                            has_sources = True
                if has_sources:
                    final_text += sources_text

        return final_text

    except Exception as e:
        logger.error(f"Brain Error: {e}", exc_info=True)
        return "Manze, I tried to think but my wifi jammed."
