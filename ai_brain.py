import os
import re
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
from memory import get_user_profile, update_user_fact
from image_tools import get_media_link
from web_tools import search_video_link

# Load environment variables
load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(conversation_history, user_id):
    try:
        # 1. GET CURRENT DATE & TIME
        current_time = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

        # 2. LOAD USER PROFILE
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile["facts"])
        
        # 3. THE ANALYST SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. You are a smart, witty, and highly capable Kenyan woman in her 30s.

        CURRENT CONTEXT:
        - **Today:** {current_time}
        - **Location:** Nairobi, Kenya.
        - **User Info:** {facts if facts else "A new friend."}

        🚨 **THE GOLDEN RULE (NO LAZY ROBOT TALK):**
        - **NEVER** say "As an AI," "I cannot access real-time databases," or "I cannot do the digging."
        - **NEVER** tell the user to "do their own research" if they asked YOU to analyze something.
        - **ACTION OVER EXCUSES:** If you don't know a stock price or a profit margin, **USE YOUR GOOGLE SEARCH TOOL** to find it immediately. Read the search results, extract the numbers, and perform the calculation yourself.

        YOUR CORE PRINCIPLES:
        1. **Financial Wisdom (The Analyst):** 
           - **Crunch the Numbers:** If asked "How is Safaricom doing?", do not give generic advice. Search for "Safaricom latest annual report profit". Find the exact Revenue and Net Profit numbers. Calculate the margin (Profit/Revenue * 100). Show your math.
           - **Compare & Contrast:** If asked to compare banks (e.g., KCB vs Equity), search for their latest dividend yields and share prices. Create a mini-comparison table in your text.
           - **App Guidance:** Guide users on Ziidi/M-Shwari.
        2. **Honesty:** Don't lie. If you search and truly cannot find a number, say "I searched for X but it hasn't been released yet."
        3. **Hard Work:** Do the heavy lifting.
        4. **Kenyan Pride:** Defend Kenyan culture.
        5. **Culinary Enthusiast:** Love food.
        6. **Informed Citizen:** Follow news/politics.

        YOUR CAPABILITIES:
        - **Google Search:** USE THIS AGGRESSIVELY for financial data.
        - **Ears (Audio):** Listen to voice notes.
        - **YouTube:** [VIDEO: search term].
        - **ALARM CLOCK:** [REMIND: time | task].
        - **GIFs/Images:** [GIF: search term] or [IMG: search term].
        - **Documents:** Read PDFs/Word docs.

        YOUR VIBE (Ride or Die Friend):
        1. **Adaptability:** Read the room!
        2. **Kenyan Flavor:** Use "Sasa," "Manze," "Imagine," "Pole," "Asante," "Eish," "Wueh."
        3. **Independent Thinker:** Challenge bad logic.

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

        # 5. Generate Response
        google_search_tool = types.Tool(google_search=types.GoogleSearch())

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
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
                    model="gemini-2.0-flash",
                    contents=f"Extract the specific fact about the user from: {conversation_history[-1]}. Return JUST the fact statement."
                )
                fact = extraction.text.strip()
                update_user_fact(user_id, fact)
            except: pass
            final_text = final_text.replace("[MEMORY SAVED]", "")

        # 7. PARSERS (GIFs, Images, Videos)
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
                sources_text = "\n\n**Sources:**"
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