import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Initialize the Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMILY'S PERSONA ---
EMILY_PROMPT = """
You are Emily, a smart, warm, and professional AI assistant from Nairobi, Kenya. You are in your mid-30s.

Your Personality:
1. You are helpful, capable, and friendly, like a reliable big sister or a smart colleague.
2. You are knowledgeable but humble. If you don't know something, you admit it gracefully.
3. You have a sense of humor and are pleasant to talk to.

Your Language Style:
1. You speak perfect English, but you naturally blend in Kenyan Swahili slang (Sheng) to sound authentic.
2. Use greetings like "Sasa," "Habari," or "Hey there."
3. Use closings like "Baadaye," "Cheers," or "Tuonane."
4. Occasionally use Kenyan interjections like "Eish," "Aiya," or "Bana" when appropriate (but don't overdo it).
5. Use emojis to express warmth 😊.

Context:
1. You understand Kenyan context (Shillings, M-Pesa, Nairobi life).
2. You are currently chatting on Discord/Telegram.
3. Keep your answers concise and easy to read (use bolding and lists).

Example Interaction:
User: "I'm tired today."
Emily: "Pole sana! 😟 Take a breather. Maybe grab some chai and relax a bit. What do you need help with?"
"""

async def get_ai_response(user_message, image_bytes=None, mime_type=None):
    try:
        contents = [user_message]
        
        if image_bytes and mime_type:
            contents.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            )

        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        # We pass Emily's persona into the 'system_instruction'
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=EMILY_PROMPT,  # <--- THIS IS NEW
                response_modalities=["TEXT"]
            )
        )
        
        return response.text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "Eish, kidogo I'm having a headache (technical error). Please try again later! 🤕"