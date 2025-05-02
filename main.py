from fastapi import FastAPI
from contextlib import asynccontextmanager
from routes import users, friends, duels
from db import init_supabase           # ← import your init function

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_supabase()               # initialize Supabase client on startup
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(users.router)
app.include_router(friends.router)
app.include_router(duels.router)