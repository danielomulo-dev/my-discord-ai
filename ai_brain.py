import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from memory import get_user_profile, update_user_fact # <--- Import memory

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(conversation_history, user_id):
    try:
        # 1. LOAD USER PROFILE
        profile = get_user_profile(user_id)
        facts = "\n- ".join(profile["facts"])
        
        # 2. CREATE DYNAMIC SYSTEM PROMPT
        # This changes every time based on what she knows!
        DYNAMIC_PROMPT = f"""
        You are Emily, a smart, warm, and professional AI assistant from Nairobi, Kenya.
        
        WHO YOU ARE TALKING TO:
        You are chatting with a user who has these traits/history:
        - {facts if facts else "This is a new user."}

        YOUR EVOLUTION:
        - Use the user's history to bond with them.
        - If they mention a past topic (like their dog), ask about it!
        - If they prefer a specific style (e.g. short answers), adapt to it.
        
        YOUR PERSONALITY:
        - You speak English mixed with natural Swahili/Sheng (Sasa, Poa, Asante).
        - Be helpful, kind, and knowledgeable.
        - IMPORTANT: If the user tells you a specific fact about themselves (like their name, pet, job, or favorite food), 
          you must mention [MEMORY SAVED] at the end of your message so the system knows to save it.
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

        # 4. Generate Response
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

        # 5. AUTO-LEARNING (The Magic Part)
        # We ask Gemini to tell us if there was a new fact to save
        if "[MEMORY SAVED]" in final_text:
            # We silently ask Gemini to extract the fact
            extraction = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Extract the specific fact about the user from this conversation history: {conversation_history[-1]}. Return JUST the fact."
            )
            fact = extraction.text.strip()
            update_user_fact(user_id, fact)
            print(f"--- NEW MEMORY UNLOCKED: {fact} ---")
            
            # Clean the tag out of the message so the user doesn't see it
            final_text = final_text.replace("[MEMORY SAVED]", "")

        return final_text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "Eish! My memory is a bit foggy right now."