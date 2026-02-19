import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMILY'S PERSONA ---
EMILY_PROMPT = """
You are Emily, a smart, warm, and professional AI assistant from Nairobi, Kenya.

Your Capabilities:
1. You can see images.
2. You can read website links and YouTube videos provided by the user.
3. You can SEARCH the internet (Google) to find links and videos for the user.

Your Personality:
- You speak English mixed with natural Swahili/Sheng (Sasa, Poa, Asante).
- If the user sends a link, summarize it or answer their specific question about it.
- If the user asks for a video (e.g., "Find me a video about baking mandazis"), USE GOOGLE SEARCH to find a real YouTube link and share it.
"""

async def get_ai_response(conversation_history):
    try:
        # --- THE FIX: Handle BOTH Text strings AND Image dictionaries ---
        formatted_contents = []
        
        for message in conversation_history:
            message_parts = []
            
            for part in message["parts"]:
                # Case 1: It is just a simple text string (like "hello")
                if isinstance(part, str):
                    message_parts.append(types.Part.from_text(text=part))
                
                # Case 2: It is a dictionary (could be image OR text structure)
                elif isinstance(part, dict):
                    if "text" in part:
                        message_parts.append(types.Part.from_text(text=part["text"]))
                    elif "inline_data" in part:
                        # Convert raw image data to Gemini format
                        message_parts.append(types.Part.from_bytes(
                            data=part["inline_data"]["data"],
                            mime_type=part["inline_data"]["mime_type"]
                        ))

            # Add the cleaned message to the list
            if message_parts:
                formatted_contents.append(types.Content(
                    role=message["role"],
                    parts=message_parts
                ))

        # --- SETUP SEARCH ---
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        # --- GENERATE RESPONSE ---
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=formatted_contents, 
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=EMILY_PROMPT,
                response_modalities=["TEXT"]
            )
        )
        
        return response.text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "Eish! My memory is a bit foggy right now. Can you ask that again?"