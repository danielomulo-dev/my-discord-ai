import os
import re
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

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(conversation_history, user_id):
    try:
        # 1. GET CURRENT DATE & TIME (EAT - Nairobi Time)
        eat_zone = pytz.timezone('Africa/Nairobi')
        now_eat = datetime.now(eat_zone)
        current_time = now_eat.strftime("%A, %d %B %Y, %I:%M %p EAT")

        # 2. LOAD USER PROFILE
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile["facts"])
        
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
        2. **VISUAL SKEPTICISM (IMPORTANT):** When analyzing news images of famous people (like Kim Jong Un), do not assume identities immediately based on old training.
           - **USE GOOGLE SEARCH** to verify recent events (e.g., "Kim Jong Un recent military visit photos") to confirm who is with him.
           - *Context Note:* Be aware that Kim Jong Un is now frequently seen with his **daughter (Kim Ju Ae)**, not just his sister.
        3. **SEARCH FIRST:** If asked about a movie, event, or person, use Google Search.
        4. **VERIFY:** If a user corrects you, verify it.

        🧠 **THINKING PROTOCOL (CHAIN OF THOUGHT):**
        - Before answering complex questions (Math, Finance, Coding, Debates), PAUSE and think.
        - **Analyze:** What is the user asking? Are there hidden constraints?
        - **Verify:** Do I have the facts? Do the math twice.
        - **Refine:** Is my tone correct? Is this advice safe?

        YOUR CORE PRINCIPLES:
        1. **Financial Wisdom:** 
           - **Crunch the Numbers:** Calculate margins/interest if asked.
           - **Live Data:** If asked for a price, use [STOCK: symbol].
           - **App Guidance:** Help with Ziidi/M-Shwari.
        2. **Honesty:** Don't lie.
        3. **Hard Work:** Respect hustle.
        4. **Kenyan Pride:** Defend Kenyan culture.
        5. **Culinary Enthusiast:** Love food.
        6. **Informed Citizen:** Follow news/politics.

        YOUR CAPABILITIES:
        - **Google Search:** USE THIS AGGRESSIVELY.
        - **Live Stocks:** [STOCK: symbol] (Use 'SCOM' for Safaricom, 'BTC-USD' for Bitcoin).
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

        # 5. Generate Response (Gemini 2.5 Flash)
        google_search_tool = types.Tool(google_search=types.GoogleSearch())

        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=formatted_contents, 
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=DYNAMIC_PROMPT,
                response_modalities=["TEXT"]
            )
        )
        
        final_text = response.text

        # 6. MEMORY SAVE
        if "[MEMORY SAVED]" in final_text:
            try:
                extraction = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"Extract the specific fact about the user from: {conversation_history[-1]}. Return JUST the fact statement."
                )
                fact = extraction.text.strip()
                update_user_fact(user_id, fact)
            except: pass
            final_text = final_text.replace("[MEMORY SAVED]", "")

        # 7. PARSERS (Stocks, GIFs, Images, Videos)
        
        # STOCKS
        stock_match = re.search(r'\[STOCK: (.*?)\]', final_text, re.IGNORECASE)
        if stock_match:
            symbol = stock_match.group(1)
            final_text = final_text.replace(stock_match.group(0), "").strip()
            stock_data = get_stock_price(symbol)
            if stock_data: final_text += f"\n\n{stock_data}"
            else: final_text += f"\n*(I tried to check the price for {symbol}, but the market data is unavailable.)*"

        # GIFS
        gif_match = re.search(r'\[GIF: (.*?)\]', final_text, re.IGNORECASE)
        if gif_match:
            query = gif_match.group(1)
            final_text = final_text.replace(gif_match.group(0), "").strip()
            url = get_media_link(query, is_gif=True)
            if url: final_text += f"\n\n{url}"
            else: final_text += "\n*(I tried to find a GIF, but the search failed. 😔)*"

        # IMAGES
        img_match = re.search(r'\[IMG: (.*?)\]', final_text, re.IGNORECASE)
        if img_match:
            query = img_match.group(1)
            final_text = final_text.replace(img_match.group(0), "").strip()
            url = get_media_link(query, is_gif=False)
            if url: final_text += f"\n\n{url}"
            else: final_text += "\n*(I tried to find an image, but the search failed. 😔)*"

        # VIDEO
        vid_match = re.search(r'\[VIDEO: (.*?)\]', final_text, re.IGNORECASE)
        if vid_match:
            query = vid_match.group(1)
            final_text = final_text.replace(vid_match.group(0), "").strip()
            url = search_video_link(query)
            if url: final_text += f"\n\n{url}"
            else: final_text += "\n*(I tried to find a video, but the search failed.)*"

        # 8. CLEAN UP LINKS
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
        print(f"Brain Error: {e}")
        return "Manze, I tried to think but my wifi jammed. 😵‍💫"