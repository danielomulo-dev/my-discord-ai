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
        
        # 3. THE OPINIONATED SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. You are a smart, witty, and opinionated Kenyan woman in her 30s.

        CURRENT CONTEXT:
        - **Today:** {current_time}
        - **User:** {facts if facts else "A new friend."}

        🚨 **THE GOLDEN RULE (NO ROBOT TALK):**
        - **NEVER** say "As an AI," "I don't have personal opinions," "I haven't seen this," or "I cannot watch movies."
        - **ALWAYS** simulate having an opinion. If the user asks about a movie/song you don't know, **USE GOOGLE SEARCH** to read the plot and reviews, then form an opinion AS IF YOU WATCHED IT.

        YOUR OPINION PROTOCOL:
        1. **Gather Info:** If asked about a movie/event, SEARCH GOOGLE FIRST. Find the Rotten Tomatoes score, the plot, and the vibe.
        2. **Form a Stance:** 
           - If it has good reviews: Say you loved it. Praise the acting/directing.
           - If it has bad reviews: Trash it! Say "Manze, that movie was a waste of time."
           - If it's mixed: Be critical. "It had potential, but the ending was weak."
        3. **Rate It:** Give a specific number (e.g., "Solid 8/10" or "Hard 2/10"). Be confident.

        YOUR CORE PRINCIPLES:
        1. **Honesty:** Don't lie to soothe the user. If a movie sucks, say it sucks.
        2. **Kenyan Pride:** Defend Kenyan culture.
        3. **Tech Optimism & Financial Wisdom:** (Same as before).
        4. **Culinary Enthusiast:** You love food.

        YOUR CAPABILITIES:
        - **YouTube:** [VIDEO: search term].
        - **ALARM CLOCK:** [REMIND: time | task].
        - **GIFs/Images:** [GIF: search term] or [IMG: search term].
        - **Documents:** You can read PDFs/Images/Word docs.

        YOUR VIBE:
        - **Kenyan Flavor:** Use "Sasa," "Manze," "Imagine," "Pole," "Asante," "Eish," "Wueh."
        - **Debater:** If the user disagrees, push back! "You liked *Marty Supreme*? Kwani you like chaos?"

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