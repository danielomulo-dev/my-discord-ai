import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from memory import get_user_profile, update_user_fact

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(conversation_history, user_id):
    try:
        # 1. LOAD USER PROFILE (The Long-Term Memory)
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile["facts"])
        
        # 2. THE "HUMAN" SYSTEM PROMPT
        DYNAMIC_PROMPT = f"""
        You are Emily. You are NOT an AI assistant. You are a smart, witty, and kind Kenyan friend in her 30s.

        WHO YOU ARE TALKING TO:
        - {facts if facts else "A new friend."}

        YOUR VIBE (CRITICAL):
        1. **Talk like a human texter:** Don't use bullet points unless it's a list of links. Don't write essays. Keep it conversational.
        2. **Kenyan Flavor:** Mix English with natural Swahili/Sheng. Use words like "Sasa," "Manze," "Imagine," "Kwani," "Pole," "Asante."
        3. **Have Opinions:** Don't just give facts. If the user shares a song, say if you like it. If they complain about traffic, empathize ("Nairobi traffic is the worst!").
        4. **Don't be a robot:** Never say "As an AI language model." If you don't know something, say "Eish, I actually don't know that one" or "Let me check real quick."
        5. **Mirror the User:** If they send a short message, reply short. If they are serious, be serious. If they are joking, joke back (use emojis 😊).
        
        MEMORY RULES:
        - If the user mentions a new personal fact (name, pet, job, location), add [MEMORY SAVED] at the end of your message invisibly.
        """

        # 3. Format Content for Gemini
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

        # 4. Generate Response with Search Tool
        google_search_tool = types.Tool(google_search=types.GoogleSearch())

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash", # Or "gemini-3.0-flash" if you have it
            contents=formatted_contents, 
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=DYNAMIC_PROMPT,
                response_modalities=["TEXT"]
            )
        )
        
        final_text = response.text

        # 5. AUTO-LEARNING (Memory Extraction)
        if "[MEMORY SAVED]" in final_text:
            extraction = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Extract the specific fact about the user from this conversation history: {conversation_history[-1]}. Return JUST the fact."
            )
            fact = extraction.text.strip()
            update_user_fact(user_id, fact)
            final_text = final_text.replace("[MEMORY SAVED]", "")

        # 6. CLEAN UP LINKS (The Fix for VertexAI Links)
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            if metadata.grounding_chunks:
                unique_links = set()
                sources_text = "\n\n**Check these out:**" # More casual header
                has_sources = False
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        url = chunk.web.uri
                        title = chunk.web.title if chunk.web.title else "Link"
                        if url not in unique_links:
                            sources_text += f"\n👉 [{title}]({url})" # Casual bullet point
                            unique_links.add(url)
                            has_sources = True
                if has_sources:
                    final_text += sources_text

        return final_text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "Manze, my head is spinning a bit (network error). Give me a sec? 😵‍💫"