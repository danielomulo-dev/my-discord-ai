import edge_tts
import re
import os

# The specific Kenyan Female Voice
VOICE = "en-KE-AsiliaNeural"

async def generate_voice_note(text, filename="reply.mp3"):
    """Converts text to an MP3 file with a Kenyan accent."""
    try:
        # 1. Clean the text (Remove things we don't want spoken)
        
        # Remove [TAGS] like [GIF: ...] or [VIDEO: ...]
        clean_text = re.sub(r'\[.*?\]', '', text)
        
        # Remove URLs (http://...) because reading links sounds bad
        clean_text = re.sub(r'http\S+', '', clean_text)
        
        # Remove markdown formatting (*, **, _)
        clean_text = clean_text.replace('*', '').replace('_', '')
        
        # Trim if text is too long (TTS has limits)
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
    """Deletes the file after sending to save server space."""
    if os.path.exists(filename):
        os.remove(filename)