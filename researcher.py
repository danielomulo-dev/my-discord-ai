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

# ─── Hybrid Model Config ─────────────────────────────────────────────────────
# Heavy reasoning model for research; fast model as fallback
MODEL_RESEARCH = os.getenv("MODEL_RESEARCH", "gemini-2.5-flash")
MODEL_FALLBACK = os.getenv("MODEL_CHAT", "gemini-2.0-flash")
RESEARCH_TIMEOUT = int(os.getenv("RESEARCH_TIMEOUT", "90"))
MAX_SOURCES = int(os.getenv("RESEARCH_MAX_SOURCES", "5"))

# Cap content per source so we don't blow the context window
# ~4 chars per token → 20 000 chars ≈ 5 000 tokens per source
MAX_CHARS_PER_SOURCE = 20_000


# ─── Analyst Prompt ───────────────────────────────────────────────────────────
REPORT_PROMPT = """
You are an expert Research Analyst.
Read the raw data provided below from various websites.
Write a comprehensive, well-structured report.

Format:
- **Title** (Bold)
- **Executive Summary** (Brief overview)
- **Key Findings** (Bulleted list of facts)
- **Analysis** (Deep dive into the details)
- **Conclusion & Recommendation**
- **Sources** (List the URLs used)

Tone: Professional, Insightful, and Kenyan-friendly (clear English).
"""


async def _generate_report(raw_data: str, model: str, timeout: int) -> str:
    """Call Gemini with the scraped data and return the report text."""
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=[
                types.Part.from_text(text=REPORT_PROMPT),
                types.Part.from_text(text=raw_data),
            ],
        ),
        timeout=timeout,
    )
    return response.text


async def perform_deep_research(topic: str) -> str:
    """
    1. Searches the web for the topic.
    2. Reads up to MAX_SOURCES websites (with per-URL error handling).
    3. Compiles a detailed report using 2.5 Flash (falls back to 2.0 Flash).
    """

    # ── 1. Gather sources ─────────────────────────────────────────────────
    logger.info(f"Research started: {topic[:80]}")

    urls = get_search_results(topic, max_results=MAX_SOURCES)
    if not urls:
        return "I couldn't find any sources for that topic."

    raw_data = f"RESEARCH TOPIC: {topic}\n\n"
    sources_used = []

    for url in urls:
        try:
            # Pass higher char limit for research-depth scraping
            content = extract_text_from_url(url, max_chars=RESEARCH_MAX_CHARS)
            if not content or len(content.strip()) < 50:
                logger.warning(f"Skipped (too short / empty): {url}")
                continue
            # Truncate oversized pages to stay within context limits
            if len(content) > MAX_CHARS_PER_SOURCE:
                content = content[:MAX_CHARS_PER_SOURCE] + "\n[...truncated]"
            # web_tools already adds "--- SOURCE: {url} ---" header
            raw_data += f"{content}\n"
            sources_used.append(url)
        except Exception as e:
            logger.warning(f"Failed to extract {url}: {e}")
            continue

    if not sources_used:
        return "I found some links but couldn't read any of them. The sites may be blocking bots."

    logger.info(f"Research scraped {len(sources_used)}/{len(urls)} sources for: {topic[:60]}")

    # ── 2. Generate report — hybrid model with fallback ───────────────────
    # Try the reasoning model first (deeper analysis, slower)
    try:
        logger.info(f"Generating report with {MODEL_RESEARCH}")
        report = await _generate_report(raw_data, MODEL_RESEARCH, RESEARCH_TIMEOUT)
        if report:
            return f"📊 **Deep Research Report**\n\n{report}"
    except asyncio.TimeoutError:
        logger.warning(f"{MODEL_RESEARCH} timed out after {RESEARCH_TIMEOUT}s — falling back")
    except Exception as e:
        logger.warning(f"{MODEL_RESEARCH} failed: {e} — falling back")

    # Fallback to the fast/stable model
    try:
        logger.info(f"Generating report with fallback {MODEL_FALLBACK}")
        report = await _generate_report(raw_data, MODEL_FALLBACK, 45)
        if report:
            return f"📊 **Research Report** *(standard mode)*\n\n{report}"
    except Exception as e:
        logger.error(f"Fallback model also failed: {e}")

    return "*(Both research engines failed. Try again in a bit!)*"
