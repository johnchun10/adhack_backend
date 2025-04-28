from dotenv import load_dotenv
import os
import models
from supabase import AsyncClient, acreate_client
from typing import Dict, Any

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

supabase: AsyncClient = None
ref = None

async def init_supabase():
    global supabase, ref
    if supabase is None:
        supabase = await acreate_client(url, key)
        ref = supabase.table("properties")