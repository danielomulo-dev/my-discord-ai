import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from duckduckgo_search import DDGS # <--- New Import

def extract_text_from_url(url):
    """Decides if the URL is a website or a YouTube video."""
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url)
    else:
        return get_website_content(url)

def get_website_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()    
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return f"--- WEBSITE CONTENT ({url}) ---\n{text[:5000]}..."
    except Exception as e:
        return f"[Error reading website: {e}]"

def get_youtube_transcript(url):
    try:
        video_id = None
        if "youtu.be" in url:
            video_id = url.split("/")[-1]
        elif "v=" in url:
            video_id = parse_qs(urlparse(url).query)['v'][0]
        if not video_id: return "[Error: No Video ID]"
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([t['text'] for t in transcript_list])
        return f"--- YOUTUBE TRANSCRIPT ({url}) ---\n{full_text[:6000]}..."
    except Exception as e:
        return f"[Error: {e} (Video might not have captions)]"

# --- NEW FUNCTION FOR SEARCHING REAL VIDEOS ---
def search_video_link(query):
    """Searches for a real YouTube link using DuckDuckGo."""
    try:
        print(f"🔎 Searching for video: {query}")
        with DDGS() as ddgs:
            # Search for videos specifically on YouTube
            results = list(ddgs.videos(
                keywords=f"site:youtube.com {query}",
                region="wt-wt",
                safesearch="moderate",
                max_results=1
            ))
            
            if results:
                # DuckDuckGo returns the link in the 'content' field
                video_url = results[0]['content']
                print(f"✅ Found Video: {video_url}")
                return video_url
            return None
    except Exception as e:
        print(f"❌ Video Search Error: {e}")
        return None