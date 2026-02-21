from duckduckgo_search import DDGS
import random

def get_media_link(query, is_gif=False):
    """Searches for an image or GIF URL."""
    try:
        with DDGS() as ddgs:
            # 1. Search for the media
            # type_image='gif' restricts to animated images if requested
            file_type = 'gif' if is_gif else None
            
            results = list(ddgs.images(
                keywords=query,
                region="wt-wt",
                safesearch="moderate",
                max_results=5, # Get 5 options so we can pick a random one
                type_image=file_type
            ))

            # 2. Return a random result (so she doesn't use the same GIF every time)
            if results:
                selected = random.choice(results)
                return selected['image']
            else:
                return ""
    except Exception as e:
        print(f"Image Search Error: {e}")
        return ""