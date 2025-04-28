from fastapi import FastAPI
from routes import example, friends, duels

app = FastAPI()

# Include routers from the routes folder
app.include_router(example.router)
app.include_router(friends.router)
app.include_router(duels.router)