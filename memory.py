import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# 1. Connect to MongoDB Atlas
try:
    # certifi.where() is needed to prevent SSL errors on some cloud servers
    client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
    db = client["emily_brain_db"]   # The name of your database
    users_col = db["users"]         # The collection (folder) for user profiles
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ Could not connect to MongoDB: {e}")

def get_user_profile(user_id):
    """Fetches user data from the cloud."""
    user_id = str(user_id)
    
    # Try to find the user in the database
    user_data = users_col.find_one({"_id": user_id})
    
    if user_data:
        return user_data
    else:
        # If new user, return default empty profile
        return {"_id": user_id, "facts": [], "style": "friendly"}

def update_user_fact(user_id, new_fact):
    """Adds a fact to the user's profile in the cloud."""
    user_id = str(user_id)
    
    # MongoDB magic: $addToSet only adds the fact if it doesn't exist yet (no duplicates!)
    users_col.update_one(
        {"_id": user_id},
        {"$addToSet": {"facts": new_fact}}, 
        upsert=True # Create the user if they don't exist
    )