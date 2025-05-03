from fastapi import FastAPI
from contextlib import asynccontextmanager
from routes import users, friends, duels
from db import init_supabase           # ← import your init function
import os
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_supabase()               # initialize Supabase client on startup
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(users.router)
app.include_router(friends.router)
app.include_router(duels.router)

@app.get("/")
async def root():
    return {"message": "Snipe API is running"}

# This allows the app to run both locally and on Cloud Run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)