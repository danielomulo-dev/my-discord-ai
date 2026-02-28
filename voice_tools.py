import os
import re
import asyncio
from elevenlabs.client import ElevenLabs
from elevenlabs import save
from dotenv import load_dotenv

load_dotenv()

# Initialize the Client
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

async def generate_voice_note(text, filename="reply.mp3"):
    """Generates audio using ElevenLabs (High Quality)."""
    try:
        # 1. Clean the text (Remove links and tags)
        # Remove [TAGS]
        clean_text = re.sub(r'\[.*?\]', '', text)
        # Remove URLs
        clean_text = re.sub(r'http\S+', '', clean_text)
        # Remove markdown (*, **, _)
        clean_text = clean_text.replace('*', '').replace('_', '').replace('#', '')
        
        # Limit text length to save credits (ElevenLabs is expensive!)
        if len(clean_text) > 1000:
            clean_text = clean_text[:1000] + "... (message truncated to save voice credits)."

        # 2. Generate Audio
        # We use asyncio.to_thread because ElevenLabs generation is "blocking"
        # and we don't want to freeze the bot while it generates.
        audio_generator = await asyncio.to_thread(
            client.text_to_speech.convert,
            voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
            model_id="eleven_turbo_v2_5", # Turbo is faster and cheaper for chat
            text=clean_text
        )

        # 3. Save the stream to a file
        # The generator returns bytes, we need to collect them
        audio_bytes = b"".join(audio_generator)
        
        with open(filename, "wb") as f:
            f.write(audio_bytes)
            
        return filename

    except Exception as e:
        print(f"❌ ElevenLabs Error: {e}")
        return None

def cleanup_voice_file(filename="reply.mp3"):
    """Deletes the file after sending."""
    if os.path.exists(filename):
        os.remove(filename)