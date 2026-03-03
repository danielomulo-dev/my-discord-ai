import os
import logging
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from web_tools import get_search_results, extract_text_from_url, RESEARCH_MAX_CHARS

load_dotenv()

logger = logging.getLogger(__name__)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Configuration
MODEL_RESEARCH = os.getenv("MODEL_RESEARCH", "gemini-2.5-flash")
MODEL_FALLBACK = os.getenv("MODEL_CHAT", "gemini-2.0-flash")
RESEARCH_TIMEOUT = 90
MAX_SOURCES = 5

REPORT_PROMPT = """
You are a Senior Research Analyst.
Your goal is to write a comprehensive, professional, and detailed report based ONLY on the raw data provided below.

STRUCTURE:
1. **Title** (Bold & Clear)
2. **Executive Summary** (High-level overview)
3. **Deep Dive Analysis** (Break down the topic into sub-sections. Use data, numbers, and facts from the text.)
4. **Key Trends/Statistics** (Bullet points of hard data found)
5. **Conclusion & Outlook**
6. **References** (List the URLs provided)

TONE:
- Professional but accessible (Kenyan-friendly English).
- If the raw data is thin, admit it, but squeeze every drop of value from it.
- Do NOT hallucinate facts not present in the sources.
"""

async def _generate_report(raw_data, model):
    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Part.from_text(text=REPORT_PROMPT),
            types.Part.from_text(text=raw_data),
        ]
    )
    return response.text

async def perform_deep_research(topic):
    logger.info(f"Research started: {topic}")

    # 1. Gather Sources (Now with Junk Filter)
    urls = get_search_results(topic, max_results=MAX_SOURCES)
    if not urls:
        return "I couldn't find any reliable sources for that topic. The internet might be acting up."

    raw_data = f"RESEARCH TOPIC: {topic}\n\n"
    valid_sources = 0

    # 2. Read Sources
    for url in urls:
        try:
            content = extract_text_from_url(url, max_chars=RESEARCH_MAX_CHARS)
            if len(content) > 500: # Only use if we actually got text
                raw_data += f"{content}\n"
                valid_sources += 1
        except: continue

    if valid_sources == 0:
        return "I found links, but I couldn't read the content (blocked by firewalls). Try a different topic."

    # 3. Generate Report
    try:
        report = await asyncio.wait_for(_generate_report(raw_data, MODEL_RESEARCH), timeout=RESEARCH_TIMEOUT)
        return f"📊 **Deep Research Report**\n\n{report}"
    except Exception as e:
        # Fallback to 2.0 if 2.5 fails
        try:
            report = await _generate_report(raw_data, MODEL_FALLBACK)
            return f"📊 **Research Report (Standard Mode)**\n\n{report}"
        except:
            return "Report generation failed."