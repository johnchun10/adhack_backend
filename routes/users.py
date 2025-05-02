from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import get_db
from models import (GenericResponse, UserCreate, UserProfile,
                        UserPublic, UserSearchResult, UserSettingsUpdate)

router = APIRouter(
    prefix="/users",
    tags=["Users"], # Tag for OpenAPI documentation
)

# --- Helper ---
async def _get_user_or_404(username: str) -> dict:
    """Fetches user data by username or raises HTTPException 404."""
    try:
        res = await get_db().table("users").select("id", "username", "blackout_start_hour").eq("username", username).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return res.data[0]
    except Exception as e:
        # Log error e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error fetching user")

# --- Routes ---

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=UserPublic)
async def create_user(user_in: UserCreate):
    """
    Registers a new user with a unique username upon first app launch.
    """
    try:
        # Insert user data
        res = await get_db().table("users").insert({
            "username": user_in.username,
            # blackout_start_hour defaults to NULL in DB
        }).execute()

        if not res.data:
             # This might happen if the insert fails silently, though unlikely with Supabase client
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")

        # Return the created user's public info (including the new ID)
        created_user_data = res.data[0]
        return UserPublic(id=created_user_data['id'], username=created_user_data['username'])

    except Exception as e:
        # Check for unique constraint violation (specific error code/message depends on Supabase/postgres)
        # Example: Check if 'duplicate key value violates unique constraint "users_username_key"' is in str(e)
        if "violates unique constraint" in str(e) and "users_username_key" in str(e):
             raise HTTPException(
                 status_code=status.HTTP_409_CONFLICT,
                 detail=f"Username '{user_in.username}' already exists."
             )
        # Log error e
        print(f"Error creating user: {e}") # Basic logging
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error creating user")


@router.get("/{username}", response_model=UserProfile)
async def get_user_profile(username: str):
    """
    Retrieves basic profile information, primarily the blackout_start_hour.
    """
    user_data = await _get_user_or_404(username)
    # Ensure blackout_start_hour is returned correctly (it might be None)
    return UserProfile(
        username=user_data['username'],
        blackout_start_hour=user_data.get('blackout_start_hour') # Use .get for safety
    )

@router.put("/{username}/settings", response_model=UserProfile)
async def update_user_settings(username: str, settings_in: UserSettingsUpdate):
    """
    Updates the user's 5-hour blackout start time.
    """
    user_data = await _get_user_or_404(username) # Ensure user exists

    try:
        res = await get_db().table("users").update({
            "blackout_start_hour": settings_in.blackout_start_hour
        }).eq("username", username).execute()

        # Supabase update returns data - refetch or use returned data if needed for response
        if not res.data:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update settings")

        # Return the updated profile
        updated_data = res.data[0]
        return UserProfile(
            username=updated_data['username'],
            blackout_start_hour=updated_data.get('blackout_start_hour')
        )
    except Exception as e:
        # Log error e
        print(f"Error updating settings: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error updating settings")


@router.get("/search/", response_model=List[UserSearchResult])
async def search_users(
    query: str = Query(..., min_length=1, description="Username query string"),
    # Optional: Add current_user dependency if you want to exclude self
    # current_username: Optional[str] = None
):
    """
    Searches for users by username (case-insensitive partial match).
    """
    if not query:
        return []
    try:
        # Use 'ilike' for case-insensitive search, limit results
        res = await get_db().table("users").select("username").ilike("username", f"%{query}%").limit(10).execute()

        # Filter out current user if provided
        # filtered_users = [user for user in res.data if user['username'] != current_username] if current_username else res.data

        return [UserSearchResult(**user) for user in res.data]
    except Exception as e:
         # Log error e
        print(f"Error searching users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error searching users")