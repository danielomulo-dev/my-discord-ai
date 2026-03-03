import logging
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# --- CONSTANTS ---
DEFAULT_MAX_CHARS = 3000
RESEARCH_MAX_CHARS = 15000

# --- NEWS SEARCH ---
def get_latest_news(topic, max_results=5):
    """Searches DuckDuckGo News for the latest headlines."""
    try:
        logger.info(f"Fetching news for: {topic}")
        with DDGS() as ddgs:
            # 'news' search returns titles, snippets, source, and date
            results = list(ddgs.news(
                keywords=topic,
                region="wt-wt",
                safesearch="moderate",
                max_results=max_results
            ))
            
            if not results:
                return None

            news_summary = f"📰 **Latest News: {topic}**\n"
            for r in results:
                title = r.get('title', 'No Title')
                source = r.get('source', 'Unknown')
                date = r.get('date', '')
                url = r.get('url', '#')
                # Format: • Title - Source (Date)
                news_summary += f"• [{title}]({url}) - *{source}* ({date})\n"
            
            return news_summary

    except Exception as e:
        logger.error(f"News search error: {e}")
        return None

# --- WEB SEARCH ---
def get_search_results(query, max_results=3):
    """Searches DuckDuckGo and returns a list of URLs."""
    try:
        logger.info(f"Searching: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="wt-wt", safesearch="moderate", max_results=max_results))
            urls = [r['href'] for r in results]
            return urls
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

# --- CONTENT EXTRACTION ---
def extract_text_from_url(url, max_chars=None):
    """Decides if the URL is a website or a YouTube video."""
    _max = max_chars or DEFAULT_MAX_CHARS
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url, max_chars=_max)
    else:
        return get_website_content(url, max_chars=_max)

def get_website_content(url, max_chars=None):
    """Scrape a webpage."""
    _max = max_chars or DEFAULT_MAX_CHARS
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()    
            
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return f"\n\n--- SOURCE: {url} ---\n{text[:_max]}..."
    except Exception as e:
        return f"\n[Could not read {url}: {e}]"

def get_youtube_transcript(url, max_chars=None):
    """Get YouTube captions."""
    _max = max_chars or DEFAULT_MAX_CHARS
    try:
        video_id = None
        if "youtu.be" in url: video_id = url.split("/")[-1]
        elif "v=" in url: video_id = parse_qs(urlparse(url).query)['v'][0]
        if not video_id: return ""
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([t['text'] for t in transcript_list])
        return f"\n\n--- VIDEO TRANSCRIPT: {url} ---\n{full_text[:_max]}..."
    except: return ""

def search_video_link(query):
    """Finds a specific YouTube video link."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(keywords=f"site:youtube.com {query}", max_results=1))
            if results: return results[0]['content']
            return None
    except: return None