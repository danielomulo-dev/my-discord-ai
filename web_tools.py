import logging
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# --- NEWS SEARCH (NEW) ---
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

# --- WEB SCRAPING ---
def extract_text_from_url(url, max_chars=3000):
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_transcript(url, max_chars)
    else:
        return get_website_content(url, max_chars)

def get_website_content(url, max_chars=3000):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        for script in soup(["script", "style", "nav", "footer"]):
            script.extract()    
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        text = '\n'.join(chunk for chunk in lines if chunk)
        return f"\n\n--- SOURCE: {url} ---\n{text[:max_chars]}..."
    except Exception as e:
        return f"\n[Error reading {url}: {e}]"

def get_youtube_transcript(url, max_chars=3000):
    try:
        video_id = None
        if "youtu.be" in url: video_id = url.split("/")[-1]
        elif "v=" in url: video_id = parse_qs(urlparse(url).query)['v'][0]
        if not video_id: return ""
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t['text'] for t in transcript])
        return f"\n\n--- VIDEO TRANSCRIPT: {url} ---\n{text[:max_chars]}..."
    except: return ""

def get_search_results(query, max_results=3):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return [r['href'] for r in results]
    except: return []

def search_video_link(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.videos(f"site:youtube.com {query}", max_results=1))
            if results: return results[0]['content']
            return None
    except: return None