import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# --- CONNECT TO MONGODB ---
try:
    # certifi.where() fixes SSL errors on cloud servers
    client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
    db = client["emily_brain_db"]
    users_col = db["users"]
    reminders_col = db["reminders"]
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ Could not connect to MongoDB: {e}")

# --- USER PROFILE FUNCTIONS (Long-Term Memory) ---
def get_user_profile(user_id):
    """Fetches user facts and style preferences."""
    user_id = str(user_id)
    user_data = users_col.find_one({"_id": user_id})
    if user_data:
        return user_data
    else:
        return {"_id": user_id, "facts": [], "style": "friendly", "history": []}

def update_user_fact(user_id, new_fact):
    """Adds a permanent fact about the user."""
    user_id = str(user_id)
    users_col.update_one(
        {"_id": user_id},
        {"$addToSet": {"facts": new_fact}}, 
        upsert=True
    )

# --- CHAT HISTORY FUNCTIONS (Context) ---
def add_message_to_history(user_id, role, message_parts):
    """Saves the conversation to the database."""
    user_id = str(user_id)
    
    new_message = {
        "role": role,
        "parts": message_parts,
        "timestamp": datetime.now()
    }

    # Push message & keep only last 30
    users_col.update_one(
        {"_id": user_id},
        {"$push": {"history": {"$each": [new_message], "$slice": -30}}},
        upsert=True
    )

def get_chat_history(user_id):
    """Retrieves the last 30 messages for context."""
    user_id = str(user_id)
    data = users_col.find_one({"_id": user_id}, {"history": 1})
    
    if data and "history" in data:
        # We remove the 'timestamp' before sending to Gemini to keep it clean
        clean_history = []
        for msg in data["history"]:
            clean_history.append({"role": msg["role"], "parts": msg["parts"]})
        return clean_history
    return []

# --- REMINDER FUNCTIONS (Alarm Clock) ---
def add_reminder(user_id, channel_id, remind_time, reminder_text):
    """Saves a scheduled task."""
    reminders_col.insert_one({
        "user_id": user_id,
        "channel_id": channel_id,
        "time": remind_time, # DateTime object
        "text": reminder_text,
        "status": "pending"
    })

def get_due_reminders():
    """Finds reminders that need to be sent NOW."""
    now = datetime.now()
    # Find reminders where time <= now
    return list(reminders_col.find({"time": {"$lte": now}}))

def delete_reminder(reminder_id):
    """Removes a reminder after sending."""
    reminders_col.delete_one({"_id": reminder_id})