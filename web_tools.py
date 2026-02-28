import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from duckduckgo_search import DDGS

def get_search_results(query, max_results=3):
    """Searches DuckDuckGo and returns a list of URLs."""
    try:
        print(f"🔎 Deep Researching: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="wt-wt", safesearch="moderate", max_results=max_results))
            urls = [r['href'] for r in results]
            return urls
    except Exception as e:
        print(f"❌ Search Error: {e}")
        return []

def extract_text_from_url(url):
    """Decides if the URL is a website or a YouTube video."""
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url)
    else:
        return get_website_content(url)

def get_website_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5) # 5s timeout to be fast
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove junk (scripts, styles, navbars)
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()    
            
        text = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Limit text to 3000 chars per site to save tokens
        return f"\n\n--- SOURCE: {url} ---\n{text[:3000]}..."
    except Exception as e:
        return f"\n[Could not read {url}: {e}]"

def get_youtube_transcript(url):
    try:
        video_id = None
        if "youtu.be" in url: video_id = url.split("/")[-1]
        elif "v=" in url: video_id = parse_qs(urlparse(url).query)['v'][0]
        if not video_id: return ""
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([t['text'] for t in transcript_list])
        return f"\n\n--- VIDEO TRANSCRIPT: {url} ---\n{full_text[:3000]}..."
    except: return ""

def search_video_link(query):
    """Finds a specific YouTube video link."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(keywords=f"site:youtube.com {query}", max_results=1))
            if results: return results[0]['content']
            return None
    except: return None