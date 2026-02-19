import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs

def extract_text_from_url(url):
    """Decides if the URL is a website or a YouTube video."""
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url)
    else:
        return get_website_content(url)

def get_website_content(url):
    """Reads text from a normal website."""
    try:
        # Fake a browser visit (User-Agent) so websites don't block us
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Kill all script and style elements (we just want text)
        for script in soup(["script", "style"]):
            script.extract()    

        text = soup.get_text()
        
        # Clean up the text (remove extra spaces)
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Limit to first 5000 characters to save AI memory
        return f"--- WEBSITE CONTENT START ({url}) ---\n{text[:5000]}...\n--- WEBSITE CONTENT END ---"
    except Exception as e:
        return f"[Error reading website: {e}]"

def get_youtube_transcript(url):
    """Gets the transcript (subtitles) from a YouTube video."""
    try:
        video_id = None
        # Extract Video ID from URL
        if "youtu.be" in url:
            video_id = url.split("/")[-1]
        elif "v=" in url:
            video_id = parse_qs(urlparse(url).query)['v'][0]
            
        if not video_id:
            return "[Error: Could not find Video ID]"

        # Fetch Transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Combine into one string
        full_text = " ".join([t['text'] for t in transcript_list])
        
        return f"--- YOUTUBE VIDEO TRANSCRIPT ({url}) ---\n{full_text[:6000]}...\n--- END TRANSCRIPT ---"
    except Exception as e:
        return f"[Error reading YouTube video: {e} (The video might not have captions)]"