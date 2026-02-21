import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB
try:
    client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
    db = client["emily_brain_db"]
    users_col = db["users"]
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ Could not connect to MongoDB: {e}")

# --- PROFILE FUNCTIONS (Long Term) ---
def get_user_profile(user_id):
    user_id = str(user_id)
    user_data = users_col.find_one({"_id": user_id})
    if user_data:
        return user_data
    else:
        return {"_id": user_id, "facts": [], "style": "friendly", "history": []}

def update_user_fact(user_id, new_fact):
    user_id = str(user_id)
    users_col.update_one(
        {"_id": user_id},
        {"$addToSet": {"facts": new_fact}}, 
        upsert=True
    )

# --- CHAT HISTORY FUNCTIONS (Short Term made Persistent) ---
def add_message_to_history(user_id, role, message_parts):
    """Saves a message to MongoDB."""
    user_id = str(user_id)
    
    new_message = {
        "role": role,
        "parts": message_parts
    }

    # 1. Push the new message to the history list
    users_col.update_one(
        {"_id": user_id},
        {"$push": {"history": new_message}},
        upsert=True
    )

    # 2. Keep only the last 30 messages (to save space)
    # This magic command slices the array to keep the last 30 items
    users_col.update_one(
        {"_id": user_id},
        {"$push": {"history": {"$each": [], "$slice": -30}}}
    )

def get_chat_history(user_id):
    """Retrieves the last 30 messages."""
    user_id = str(user_id)
    data = users_col.find_one({"_id": user_id}, {"history": 1})
    
    if data and "history" in data:
        return data["history"]
    return []