import logging
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# --- CONSTANTS ---
DEFAULT_MAX_CHARS = 3000
RESEARCH_MAX_CHARS = 20000 # Increased for better reports

# Domains that are usually useless for deep research reports
JUNK_DOMAINS = [
    "zhihu.com", "quora.com", "reddit.com", "stackexchange.com", 
    "stackoverflow.com", "facebook.com", "instagram.com", "twitter.com", 
    "tiktok.com", "pinterest.com", "youtube.com"
]

# --- INTELLIGENT WEB SEARCH ---
def get_search_results(query, max_results=3):
    """Searches DuckDuckGo and filters out junk sites."""
    try:
        # Append keywords to find better articles
        refined_query = f"{query} analysis report article"
        logger.info(f"Searching: {refined_query}")
        
        valid_urls = []
        
        with DDGS() as ddgs:
            # Fetch more results than we need (10) so we can filter the bad ones
            results = list(ddgs.text(refined_query, region="wt-wt", safesearch="moderate", max_results=15))
            
            for r in results:
                url = r['href']
                # Check against Junk List
                if any(junk in url for junk in JUNK_DOMAINS):
                    continue
                
                # If it passes, keep it
                valid_urls.append(url)
                
                # Stop once we have enough good links
                if len(valid_urls) >= max_results:
                    break
            
            return valid_urls

    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

# --- NEWS SEARCH ---
def get_latest_news(topic, max_results=5):
    """Searches DuckDuckGo News."""
    try:
        logger.info(f"Fetching news for: {topic}")
        with DDGS() as ddgs:
            results = list(ddgs.news(keywords=topic, region="wt-wt", safesearch="moderate", max_results=max_results))
            if not results: return None

            news_summary = f"📰 **Latest News: {topic}**\n"
            for r in results:
                title = r.get('title', 'No Title')
                source = r.get('source', 'Unknown')
                date = r.get('date', '')
                url = r.get('url', '#')
                news_summary += f"• [{title}]({url}) - *{source}* ({date})\n"
            return news_summary
    except Exception as e:
        logger.error(f"News search error: {e}")
        return None

# --- CONTENT EXTRACTION ---
def extract_text_from_url(url, max_chars=None):
    _max = max_chars or DEFAULT_MAX_CHARS
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url, max_chars=_max)
    else:
        return get_website_content(url, max_chars=_max)

def get_website_content(url, max_chars=None):
    _max = max_chars or DEFAULT_MAX_CHARS
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Aggressive cleaning
        for script in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            script.extract()    
            
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        # Filter out short navigation lines
        chunks = (phrase.strip() for line in lines for phrase in line.split("  ") if len(phrase) > 20)
        text = '\n'.join(chunks)
        
        return f"\n\n--- SOURCE: {url} ---\n{text[:_max]}..."
    except Exception as e:
        return f"\n[Could not read {url}: {e}]"

def get_youtube_transcript(url, max_chars=None):
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
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(keywords=f"site:youtube.com {query}", max_results=1))
            if results: return results[0]['content']
            return None
    except: return None