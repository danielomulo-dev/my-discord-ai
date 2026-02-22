import edge_tts
import re
import os

# The specific Kenyan Female Voice
VOICE = "en-KE-AsiliaNeural"

async def generate_voice_note(text, filename="reply.mp3"):
    """Converts text to an MP3 file with a Kenyan accent."""
    try:
        # 1. Clean the text (Remove links, tags, and excessive symbols)
        # Remove [TAGS] like [GIF: ...] or [VIDEO: ...]
        clean_text = re.sub(r'\[.*?\]', '', text)
        # Remove URLs (http://...)
        clean_text = re.sub(r'http\S+', '', clean_text)
        # Remove formatting (*, **)
        clean_text = clean_text.replace('*', '').replace('_', '')
        
        # If text is too long, trim it (TTS limit)
        if len(clean_text) > 2000:
            clean_text = clean_text[:2000] + "... check the text for more."

        # 2. Generate Audio
        communicate = edge_tts.Communicate(clean_text, VOICE)
        await communicate.save(filename)
        return filename

    except Exception as e:
        print(f"❌ TTS Error: {e}")
        return None

def cleanup_voice_file(filename="reply.mp3"):
    """Deletes the file after sending to save space."""
    if os.path.exists(filename):
        os.remove(filename)