import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime
import pytz

load_dotenv()

# --- CONNECT TO MONGODB ---
try:
    client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
    db = client["emily_brain_db"]
    users_col = db["users"]
    reminders_col = db["reminders"]
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ Could not connect to MongoDB: {e}")

# --- USER PROFILE FUNCTIONS ---

def get_user_profile(user_id):
    """Fetches user profile and flattens facts into strings for the AI prompt."""
    user_id = str(user_id)
    user_data = users_col.find_one({"_id": user_id})
    
    if not user_data:
        return {"_id": user_id, "facts": [], "style": "friendly", "history": []}
    
    # Flatten structured facts for Emily's prompt
    raw_facts = user_data.get("facts", [])
    clean_facts = []
    for f in raw_facts:
        if isinstance(f, dict):
            clean_facts.append(f.get("fact", ""))
        else:
            clean_facts.append(str(f))
            
    user_data["facts"] = clean_facts
    return user_data

def update_user_fact(user_id, fact_text, category="general"):
    """Adds a structured fact with a category and timestamp."""
    user_id = str(user_id)
    eat_zone = pytz.timezone('Africa/Nairobi')
    
    fact_entry = {
        "fact": fact_text,
        "category": category,
        "added_at": datetime.now(eat_zone)
    }

    users_col.update_one(
        {"_id": user_id},
        {"$push": {"facts": fact_entry}}, 
        upsert=True
    )

def set_voice_mode(user_id, enabled):
    """Turns voice mode ON (True) or OFF (False) for a user."""
    user_id = str(user_id)
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"voice_mode": enabled}}, 
        upsert=True
    )

# --- CHAT HISTORY FUNCTIONS ---

def add_message_to_history(user_id, role, message_parts):
    """Saves the conversation to the database."""
    user_id = str(user_id)
    eat_zone = pytz.timezone('Africa/Nairobi')
    
    new_message = {
        "role": role,
        "parts": message_parts,
        "timestamp": datetime.now(eat_zone)
    }

    users_col.update_one(
        {"_id": user_id},
        {"$push": {"history": {"$each": [new_message], "$slice": -30}}},
        upsert=True
    )

def get_chat_history(user_id):
    """Retrieves the last 30 messages."""
    user_id = str(user_id)
    data = users_col.find_one({"_id": user_id}, {"history": 1})
    
    if data and "history" in data:
        return [{"role": msg["role"], "parts": msg["parts"]} for msg in data["history"]]
    return []

# --- REMINDER FUNCTIONS ---

def add_reminder(user_id, channel_id, remind_time, reminder_text):
    """Saves a scheduled task."""
    reminders_col.insert_one({
        "user_id": user_id,
        "channel_id": channel_id,
        "time": remind_time, 
        "text": reminder_text,
        "status": "pending"
    })

def get_due_reminders():
    """Finds reminders that need to be sent NOW."""
    eat_zone = pytz.timezone('Africa/Nairobi')
    now_eat = datetime.now(eat_zone)
    return list(reminders_col.find({"time": {"$lte": now_eat}}))

def delete_reminder(reminder_id):
    """Removes a reminder after sending."""
    reminders_col.delete_one({"_id": reminder_id})