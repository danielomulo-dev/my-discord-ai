import json
import os

MEMORY_FILE = "user_data.json"

def load_memory():
    """Loads the database of users."""
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_memory(data):
    """Saves the database."""
    with open(MEMORY_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_user_profile(user_id):
    """Gets the facts we know about a specific user."""
    data = load_memory()
    return data.get(str(user_id), {"facts": [], "style": "friendly"})

def update_user_fact(user_id, new_fact):
    """Adds a new fact about the user."""
    data = load_memory()
    user_id = str(user_id)
    
    if user_id not in data:
        data[user_id] = {"facts": [], "style": "friendly"}
    
    # Avoid duplicates
    if new_fact not in data[user_id]["facts"]:
        data[user_id]["facts"].append(new_fact)
        save_memory(data)