import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Initialize the Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(user_message, image_bytes=None, mime_type=None):
    try:
        # 1. Start the content list with the user's text
        contents = [user_message]
        
        # 2. If there is an image, add it to the message
        if image_bytes and mime_type:
            contents.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            )

        # 3. Enable Google Search Tool (Grounding)
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        # 4. Generate content with search enabled
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                response_modalities=["TEXT"]
            )
        )
        
        return response.text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "I'm having trouble seeing or searching right now. Please try again."