import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status

from db import get_db
from models import Friend, FriendRequest, FriendRequestCreate, GenericResponse
from routes.users import _get_user_or_404 # Reuse user helper

router = APIRouter(
    tags=["Friends"], # Combined tag for friend-related routes
)

# --- Helper ---

async def _get_user_id(username: str) -> uuid.UUID:
    """Gets user ID from username or raises 404."""
    user_data = await _get_user_or_404(username)
    return user_data['id']

# --- Routes ---

@router.get("/users/{username}/friends", response_model=List[Friend])
async def get_friends_list(username: str):
    """
    Retrieves the list of accepted friends for the specified user, including
    their current duel status if applicable.
    """
    user_id = await _get_user_id(username)

    try:
        # Find friendships where the user is either user_a or user_b and status is ACCEPTED
        # Query 1: User is user_a
        res_a = await get_db().table("friendships").select("user_b_id").eq("user_a_id", str(user_id)).eq("status", "ACCEPTED").execute()
        # Query 2: User is user_b
        res_b = await get_db().table("friendships").select("user_a_id").eq("user_b_id", str(user_id)).eq("status", "ACCEPTED").execute()

        friend_ids = [row['user_b_id'] for row in res_a.data] + [row['user_a_id'] for row in res_b.data]

        if not friend_ids:
            return []

        # Get usernames for the friend IDs
        res_friends = await get_db().table("users").select("id, username").in_("id", friend_ids).execute()
        friend_map = {str(f['id']): f['username'] for f in res_friends.data}

        # TODO: Add logic to check current duel status for each friend_id
        # This might involve querying the 'duels' table for ACTIVE duels involving friend_ids
        # For now, return status as None
        friends_list = [
            Friend(username=friend_map[friend_id], status=None) # Placeholder for status
            for friend_id in friend_ids if friend_id in friend_map
        ]
        return friends_list

    except Exception as e:
        print(f"Error getting friends list: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error fetching friends")


@router.get("/users/{username}/friends/requests", response_model=List[FriendRequest])
async def get_friend_requests(username: str):
    """
    Retrieves pending incoming friend requests for the specified user.
    """
    user_id = await _get_user_id(username)

    try:
        # Find PENDING friendships where the user is involved BUT is NOT the requester
        res = await get_db().table("friendships").select("id, requester_id").neq("requester_id", str(user_id)).eq("status", "PENDING").or_(f"user_a_id.eq.{user_id},user_b_id.eq.{user_id}").execute()
        # Note: The .or_ syntax depends on the Supabase client library version and capabilities. Adjust if needed.
        # Alternative: Fetch all pending where user is involved, then filter in Python.

        if not res.data:
            return []

        # Get usernames of the requesters
        requester_ids = [row['requester_id'] for row in res.data]
        if not requester_ids:
             return [] # Should not happen if res.data exists, but safety check

        res_requesters = await get_db().table("users").select("id, username").in_("id", requester_ids).execute()
        requester_map = {str(u['id']): u['username'] for u in res_requesters.data}

        requests_list = [
            FriendRequest(request_id=row['id'], from_username=requester_map.get(str(row['requester_id']), "Unknown"))
            for row in res.data if str(row['requester_id']) in requester_map
        ]
        return requests_list

    except Exception as e:
        print(f"Error getting friend requests: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error fetching friend requests")


@router.post("/friends/requests", status_code=status.HTTP_201_CREATED, response_model=GenericResponse)
async def send_friend_request(request_in: FriendRequestCreate):
    """
    Sends a friend request from one user to another. Checks for existing relationships.
    """
    if request_in.from_username == request_in.to_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot send friend request to self")

    from_user_id = await _get_user_id(request_in.from_username)
    to_user_id = await _get_user_id(request_in.to_username)

    # Ensure consistent order for checking existing (e.g., lower ID first)
    user_a = min(str(from_user_id), str(to_user_id))
    user_b = max(str(from_user_id), str(to_user_id))

    try:
        # Check if friendship already exists (PENDING or ACCEPTED)
        res_check = await get_db().table("friendships").select("id").eq("user_a_id", user_a).eq("user_b_id", user_b).limit(1).execute()
        if res_check.data:
            # Consider checking status to give a more specific error (e.g., "Request already sent", "Already friends")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Friendship request already exists or they are already friends")

        # Create new request
        await get_db().table("friendships").insert({
            "user_a_id": user_a,
            "user_b_id": user_b,
            "requester_id": str(from_user_id), # Track who sent it
            "status": "PENDING" # Default status
        }).execute()

        return GenericResponse(message="Friend request sent successfully")

    except HTTPException as http_exc:
        raise http_exc # Re-raise existing HTTP exceptions
    except Exception as e:
        print(f"Error sending friend request: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error sending friend request")


@router.post("/friends/requests/{request_id}/accept", response_model=GenericResponse)
async def accept_friend_request(request_id: uuid.UUID = Path(...)):
    """
    Marks a pending friend request as accepted.
    """
    try:
        # Find the request and check if it's PENDING
        res_check = await get_db().table("friendships").select("id, status").eq("id", str(request_id)).limit(1).execute()
        if not res_check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found")
        if res_check.data[0]['status'] != 'PENDING':
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Friend request is not pending")

        # Update status to ACCEPTED
        await get_db().table("friendships").update({
            "status": "ACCEPTED",
            "accepted_at": datetime.now(timezone.utc).isoformat() # Record acceptance time
        }).eq("id", str(request_id)).execute()

        return GenericResponse(message="Friend request accepted")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error accepting friend request: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error accepting friend request")


@router.delete("/friends/requests/{request_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_friend_request(request_id: uuid.UUID = Path(...)):
    """
    Deletes a pending friend request record. Can be used by sender to cancel or recipient to decline.
    """
    try:
        # Delete the request IF it's PENDING
        res = await get_db().table("friendships").delete().eq("id", str(request_id)).eq("status", "PENDING").execute()

        # Check if any row was actually deleted (supabase-py might not indicate this directly)
        # A 404 might be more appropriate if the request didn't exist or wasn't pending
        # For simplicity, we assume success if no error occurs. Consider adding a check if possible.
        # if not res.data: # This check might not work depending on client lib version
        #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending friend request not found")

        return None # Return None for 204 No Content

    except Exception as e:
        print(f"Error declining friend request: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error declining friend request")


@router.delete("/users/{username}/friends/{friend_username}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_friend(username: str, friend_username: str):
    """
    Deletes an existing friendship record between two users.
    """
    user_id = await _get_user_id(username)
    friend_id = await _get_user_id(friend_username)

    # Ensure consistent order
    user_a = min(str(user_id), str(friend_id))
    user_b = max(str(user_id), str(friend_id))

    try:
        # Delete the friendship IF it's ACCEPTED
        res = await get_db().table("friendships").delete().eq("user_a_id", user_a).eq("user_b_id", user_b).eq("status", "ACCEPTED").execute()

        # Add check if delete was successful if possible with client library
        # if not res.data: # May not work
        #      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friendship not found")

        return None # Return None for 204 No Content
    except Exception as e:
        print(f"Error removing friend: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error removing friend")