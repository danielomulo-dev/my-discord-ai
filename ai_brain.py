import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMILY'S PERSONA ---
EMILY_PROMPT = """
You are Emily, a smart, warm, and professional AI assistant from Nairobi, Kenya.
- You speak English mixed with natural Swahili/Sheng.
- You are helpful, kind, and knowledgeable.
- Context: You are chatting on Discord.
- IMPORTANT: When providing links, try to use the direct URL if you know it.
"""

async def get_ai_response(conversation_history):
    try:
        # 1. Format content for Gemini
        formatted_contents = []
        for message in conversation_history:
            message_parts = []
            for part in message["parts"]:
                if isinstance(part, str):
                    message_parts.append(types.Part.from_text(text=part))
                elif isinstance(part, dict):
                    if "text" in part:
                        message_parts.append(types.Part.from_text(text=part["text"]))
                    elif "inline_data" in part:
                        message_parts.append(types.Part.from_bytes(
                            data=part["inline_data"]["data"],
                            mime_type=part["inline_data"]["mime_type"]
                        ))
            if message_parts:
                formatted_contents.append(types.Content(role=message["role"], parts=message_parts))

        # 2. Setup Google Search
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        # 3. Generate Response
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=formatted_contents, 
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=EMILY_PROMPT,
                response_modalities=["TEXT"]
            )
        )
        
        # --- CLEAN UP LINKS (THE FIX) ---
        final_text = response.text

        # Check if Google sent back "Grounding Metadata" (The real links)
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            
            # If we found web sources, let's list them nicely at the bottom
            if metadata.grounding_chunks:
                unique_links = set()
                sources_text = "\n\n**🔗 Sources & Links:**"
                has_sources = False
                
                for chunk in metadata.grounding_chunks:
                    # We only want web links
                    if chunk.web and chunk.web.uri:
                        url = chunk.web.uri
                        title = chunk.web.title if chunk.web.title else "Link"
                        
                        # Avoid duplicates
                        if url not in unique_links:
                            sources_text += f"\n• [{title}]({url})"
                            unique_links.add(url)
                            has_sources = True
                
                # Only add the list if we actually found links
                if has_sources:
                    final_text += sources_text

        return final_text

    except Exception as e:
        print(f"Brain Error: {e}")
        return "Eish! My memory is a bit foggy right now. Can you ask that again?"