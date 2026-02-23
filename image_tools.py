from duckduckgo_search import DDGS
import random

def get_media_link(query, is_gif=False):
    """Searches for an image or GIF URL using DuckDuckGo."""
    try:
        # Clean the query (remove quotes or dots at the end)
        clean_query = query.strip(' ".,!')
        print(f"🔎 Searching for: '{clean_query}' (GIF: {is_gif})")

        with DDGS() as ddgs:
            # 'gif' type restricts results to animated images
            file_type = 'gif' if is_gif else None
            
            # Search
            results = list(ddgs.images(
                keywords=clean_query,
                region="wt-wt",
                safesearch="moderate",
                max_results=10,
                type_image=file_type
            ))

            if results:
                # Pick a random one from the top 10 so it's not boring
                selected = random.choice(results)
                image_url = selected.get('image', '')
                print(f"✅ Found Image: {image_url}")
                return image_url
            else:
                print("❌ No results found.")
                return None

    except Exception as e:
        print(f"❌ Image Search Error: {e}")
        return None