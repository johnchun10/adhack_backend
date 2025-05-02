from dotenv import load_dotenv
import os
import models
from supabase import AsyncClient, acreate_client
from typing import Dict, Any

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

db: AsyncClient = None

async def init_supabase():
    global db
    if db is None:
        print("Initializing Supabase client...")
        db = await acreate_client(url, key)
        print("Supabase client initialized successfully")

def get_db():
    """Returns the initialized Supabase client.
    Make sure this is called after lifespan has run init_supabase()."""
    if db is None:
        raise RuntimeError("Supabase client not initialized. Make sure lifespan has run init_supabase()")
    return db