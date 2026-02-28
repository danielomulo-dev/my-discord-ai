import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from web_tools import get_search_results, extract_text_from_url

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def perform_deep_research(topic):
    """
    1. Searches for the topic.
    2. Reads the top 3 websites.
    3. Compiles a detailed report.
    """
    # 1. Gather Data
    urls = get_search_results(topic, max_results=3)
    if not urls:
        return "I couldn't find any sources for that topic."

    raw_data = f"RESEARCH TOPIC: {topic}\n"
    
    for url in urls:
        content = extract_text_from_url(url)
        raw_data += content

    # 2. The Analyst Prompt
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

    # 3. Generate Report using Gemini
    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_text(text=REPORT_PROMPT),
                types.Part.from_text(text=raw_data)
            ]
        )
        return response.text
    except Exception as e:
        return f"Research failed: {e}"