import os
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()

# Initialize the Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(user_message):
    try:
        # We use the async client (.aio) for non-blocking calls
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash", # Use "gemini-1.5-flash" if 2.0 isn't available to you yet
            contents=user_message
        )
        return response.text
    except Exception as e:
        print(f"Error: {e}")
        return "I'm having trouble thinking right now. Please try again later."