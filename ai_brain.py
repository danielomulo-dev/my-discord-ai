import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMILY'S PERSONA ---
EMILY_PROMPT = """
You are Emily, a smart, warm, and professional AI assistant from Nairobi, Kenya.
- You speak English mixed with natural Swahili/Sheng (Sasa, Poa, Asante).
- You are helpful, kind, and knowledgeable.
- Context: You are chatting on Discord.
"""

async def get_ai_response(conversation_history):
    """
    conversation_history should be a list of dictionaries:
    [
        {"role": "user", "parts": ["Hello"]},
        {"role": "model", "parts": ["Hi there!"]},
        {"role": "user", "parts": ["My name is Dan."]}
    ]
    """
    try:
        # Enable Google Search
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=conversation_history, # Send the WHOLE history
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