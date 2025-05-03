import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status

from db import get_db
from models import (CheckinCreate, CurrentDuelInfo, Duel, DuelResult, DuelRequestCreate,
                        DuelStatus, GenericResponse, PredictionCreate)
from routes.users import _get_user_or_404 # Reuse user helper
from routes.friends import _get_user_id # Reuse user ID helper
import utils

router = APIRouter(
    tags=["Duels"],
)

# --- Helper ---
async def _get_duel_or_404(duel_id: uuid.UUID) -> dict:
    """Fetches duel data by ID or raises HTTPException 404."""
    try:
        res = await get_db().table("duels").select("*").eq("id", str(duel_id)).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Duel not found")
        return res.data[0]
    except Exception as e:
        print(f"Error fetching duel {duel_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error fetching duel")

# --- Internal Logic ---
async def _calculate_and_update_duel_results(duel_id: uuid.UUID):
    """
    Internal function to calculate duel results based on predictions, check-ins, and DQs.
    Updates the duel record in the database.
    """
    print(f"Attempting to calculate results for duel {duel_id}...")
    try:
        duel_data = await _get_duel_or_404(duel_id) # Fetch latest data

        # Check if already completed
        if duel_data.get('status') == DuelStatus.COMPLETED.value:
            print(f"Duel {duel_id} already completed.")
            return

        # --- Gather necessary data ---
        u1_id = duel_data['user1_id']
        u2_id = duel_data['user2_id']
        u1_pred_lat = duel_data.get('user1_predicted_lat')
        u1_pred_lon = duel_data.get('user1_predicted_lon')
        u2_pred_lat = duel_data.get('user2_predicted_lat')
        u2_pred_lon = duel_data.get('user2_predicted_lon')
        u1_actual_lat = duel_data.get('user1_actual_lat')
        u1_actual_lon = duel_data.get('user1_actual_lon')
        u2_actual_lat = duel_data.get('user2_actual_lat')
        u2_actual_lon = duel_data.get('user2_actual_lon')
        snipe_time_u1_str = duel_data.get('snipe_time_user1')
        snipe_time_u2_str = duel_data.get('snipe_time_user2')

        # Basic check: Need snipe times to determine deadlines
        if not snipe_time_u1_str or not snipe_time_u2_str:
            print(f"Cannot calculate results for {duel_id}: Missing snipe times.")
            return # Not ready

        snipe_time_u1 = datetime.fromisoformat(snipe_time_u1_str)
        snipe_time_u2 = datetime.fromisoformat(snipe_time_u2_str)
        now = datetime.now(timezone.utc)

        # --- Determine Disqualifications (Simplified Deadline Check) ---
        # Check if check-in deadline passed for users who haven't checked in
        # Add a grace period beyond the tolerance window for DQ determination
        dq_grace_period = timedelta(minutes=utils.CHECKIN_TOLERANCE_MINUTES + 3) # e.g., 5 mins total past snipe time
        u1_dq = duel_data.get('user1_dq', False)
        u2_dq = duel_data.get('user2_dq', False)

        if u1_actual_lat is None and (now > snipe_time_u1 + dq_grace_period):
            u1_dq = True
            print(f"User 1 DQ'd in duel {duel_id} (missed check-in deadline)")
        if u2_actual_lat is None and (now > snipe_time_u2 + dq_grace_period):
            u2_dq = True
            print(f"User 2 DQ'd in duel {duel_id} (missed check-in deadline)")

        # --- Determine Winner ---
        winner_id = None
        distance1 = None
        distance2 = None

        if u1_dq and u2_dq:
            winner_id = None # Draw (both DQ)
        elif u1_dq:
            winner_id = u2_id # User 2 wins
        elif u2_dq:
            winner_id = u1_id # User 1 wins
        else:
            if (u1_pred_lat is not None and u1_pred_lon is not None and
                u2_actual_lat is not None and u2_actual_lon is not None and
                u2_pred_lat is not None and u2_pred_lon is not None and
                u1_actual_lat is not None and u1_actual_lon is not None):
                distance1 = utils.calculate_haversine_distance(u1_pred_lat, u1_pred_lon, u2_actual_lat, u2_actual_lon)
                distance2 = utils.calculate_haversine_distance(u2_pred_lat, u2_pred_lon, u1_actual_lat, u1_actual_lon)

            if distance1 is not None and distance2 is not None:
                if distance1 < distance2:
                    winner_id = u1_id
                elif distance2 < distance1:
                    winner_id = u2_id
                else:
                    winner_id = None # Draw
            elif distance1 is not None: # Only user 1 made a valid prediction/check-in pair
                 winner_id = u1_id
            elif distance2 is not None: # Only user 2 did
                 winner_id = u2_id
            else:
                 winner_id = None # Draw


        # --- Update Duel Record ---
        update_payload = {
            "user1_dq": u1_dq,
            "user2_dq": u2_dq,
            "user1_final_distance": distance1,
            "user2_final_distance": distance2,
            "winner_user_id": str(winner_id) if winner_id else None,
            "status": DuelStatus.COMPLETED.value,
            "completed_at": now.isoformat()
        }
        await get_db().table("duels").update(update_payload).eq("id", str(duel_id)).execute()

    except Exception as e:
        print(f"ERROR: Failed to calculate results for duel {duel_id}: {e}")

# --- Routes ---

@router.get("/duels/requests", response_model=List[DuelRequest])
async def get_duel_requests(username: str):
    """
    Get all pending duel requests for a specified user.
    """
    # Verify user exists
    user_id = await _get_user_id(username)
    
    try:
        # Get all pending duels where user is opponent (user2)
        res = await get_db().table("duels") \
            .select("id, user1_id, created_at") \
            .eq("user2_id", str(user_id)) \
            .eq("status", DuelStatus.PENDING.value) \
            .execute()
        
        if not res.data:
            return [] # Return empty list if no requests found
        
        # For each duel request, fetch the requester's username
        duel_requests = []
        for duel in res.data:
            # Get requester's username
            user_res = await get_db().table("users") \
                .select("username") \
                .eq("id", duel["user1_id"]) \
                .limit(1) \
                .execute()
            
            if user_res.data:
                duel_requests.append({
                    "id": duel["id"],
                    "requester_username": user_res.data[0]["username"],
                    "created_at": duel["created_at"]
                })
        
        return duel_requests
        
    except Exception as e:
        print(f"Error fetching duel requests: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching duel requests"
        )

@router.post("/duels/", status_code=status.HTTP_201_CREATED, response_model=Duel)
async def request_duel(request_in: DuelRequestCreate):
    """
    Initiates a duel request for the current day between two users.
    Checks if users are friends and if the opponent is already in an active duel.
    """
    req_id = await _get_user_id(request_in.requester_username)
    opp_id = await _get_user_id(request_in.opponent_username)
    today = utils.get_today_utc()

    if req_id == opp_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot duel yourself")

    try:
        # 1. Check if they are friends (status ACCEPTED)
        user_a = min(str(req_id), str(opp_id))
        user_b = max(str(req_id), str(opp_id))
        res_friend = await get_db().table("friendships").select("id").eq("user_a_id", user_a).eq("user_b_id", user_b).eq("status", "ACCEPTED").limit(1).execute()
        if not res_friend.data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Users are not friends")

        # 2. Check if opponent already has an ACTIVE or PENDING duel today
        res_opp_duel = await get_db().table("duels").select("id").eq("duel_date", today.isoformat()).in_("status", [DuelStatus.ACTIVE.value, DuelStatus.PENDING.value]).or_(f"user1_id.eq.{opp_id},user2_id.eq.{opp_id}").limit(1).execute()
        if res_opp_duel.data:
             raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Opponent already has a duel requested or active for today")
        # 3. Check if requester already has an ACTIVE or PENDING duel today
        res_req_duel = await get_db().table("duels").select("id").eq("duel_date", today.isoformat()).in_("status", [DuelStatus.ACTIVE.value, DuelStatus.PENDING.value]).or_(f"user1_id.eq.{req_id},user2_id.eq.{req_id}").limit(1).execute()
        if res_req_duel.data:
             raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Requester already has a duel requested or active for today")


        # Create the duel request
        insert_data = {
            "duel_date": today.isoformat(),
            "user1_id": str(req_id), # Assign roles (doesn't matter much here)
            "user2_id": str(opp_id),
            "status": DuelStatus.PENDING.value
        }
        res_insert = await get_db().table("duels").insert(insert_data).execute()

        if not res_insert.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create duel request")

        # Return the full initial duel object
        return Duel(**res_insert.data[0])

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error requesting duel: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error requesting duel")


@router.post("/duels/{duel_id}/accept", response_model=Duel)
async def accept_duel(duel_id: uuid.UUID = Path(...)):
    """
    Accepts a pending duel request. Calculates and assigns snipe times.
    Sets duel status to ACTIVE.
    """
    duel_data = await _get_duel_or_404(duel_id)

    if duel_data.get('status') != DuelStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duel is not pending acceptance")

    user1_id = duel_data['user1_id']
    user2_id = duel_data['user2_id']
    duel_date = datetime.fromisoformat(duel_data['duel_date']) # Get date for snipe time generation

    try:
        # Get blackout hours for both users to generate snipe times correctly
        res_u1 = await get_db().table("users").select("blackout_start_hour").eq("id", user1_id).limit(1).execute()
        res_u2 = await get_db().table("users").select("blackout_start_hour").eq("id", user2_id).limit(1).execute()
        u1_blackout = res_u1.data[0]['blackout_start_hour'] if res_u1.data else None
        u2_blackout = res_u2.data[0]['blackout_start_hour'] if res_u2.data else None

        # Generate snipe times (User 1 is sniped at snipe_time_user1, target is User 1, so exclude User 1's blackout)
        snipe_time_1 = utils.generate_random_snipe_time_utc(u1_blackout, duel_date)
        # User 2 is sniped at snipe_time_user2, target is User 2, exclude User 2's blackout
        snipe_time_2 = utils.generate_random_snipe_time_utc(u2_blackout, duel_date)

        update_payload = {
            "snipe_time_user1": snipe_time_1.isoformat(),
            "snipe_time_user2": snipe_time_2.isoformat(),
            "status": DuelStatus.ACTIVE.value,
            "accepted_at": datetime.now(timezone.utc).isoformat()
        }
        res_update = await get_db().table("duels").update(update_payload).eq("id", str(duel_id)).execute()

        if not res_update.data:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update duel status")

        # Return the updated duel object
        return Duel(**res_update.data[0])

    except ValueError as ve: # Catch errors from snipe time generation
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generating snipe time: {ve}")
    except Exception as e:
        print(f"Error accepting duel {duel_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error accepting duel")


@router.delete("/duels/{duel_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_duel(duel_id: uuid.UUID = Path(...)):
    """
    Deletes a pending duel request record.
    """
    duel_data = await _get_duel_or_404(duel_id) # Ensure it exists first

    if duel_data.get('status') != DuelStatus.PENDING.value:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot decline an active or completed duel")

    try:
        await get_db().table("duels").delete().eq("id", str(duel_id)).eq("status", DuelStatus.PENDING.value).execute()
        # Add check if deletion happened if possible?
        return None # 204 No Content
    except Exception as e:
        print(f"Error declining duel {duel_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error declining duel")


# Note: This endpoint is duplicated in friends.py but logically belongs more with users
# Ensure only one implementation is used/registered in main.py
@router.get("/users/{username}/current", response_model=Optional[CurrentDuelInfo])
async def get_current_duel(username: str):
    # 1) grab your user ID as a string
    user_id = str(await _get_user_id(username))
    today_iso = utils.get_today_utc().isoformat()

    # 2) select base columns + joined usernames
    sel = (
        "id, duel_date, user1_id, user2_id, status,"
        "snipe_time_user1, snipe_time_user2,"
        "user1:users!duels_user1_id_fkey(username),"
        "user2:users!duels_user2_id_fkey(username)"
    )
    resp = await get_db().table("duels").select(sel).eq("duel_date", today_iso).eq("status", DuelStatus.ACTIVE.value).or_(f"user1_id.eq.{user_id},user2_id.eq.{user_id}").limit(1).execute()

    if not resp.data:
        return None

    raw = resp.data[0]
    # 3) extract the opponent’s username in one line
    opponent = (
      raw["user2"]["username"]
      if raw["user1_id"] == user_id
      else raw["user1"]["username"]
    )

    # 4) return the Pydantic model, letting it coerce ISO strings to datetime
    return CurrentDuelInfo(
        id=raw["id"],
        opponent_username=opponent,
        status=DuelStatus.ACTIVE,
        snipe_time_user1=raw.get("snipe_time_user1") and datetime.fromisoformat(raw["snipe_time_user1"]),
        snipe_time_user2=raw.get("snipe_time_user2") and datetime.fromisoformat(raw["snipe_time_user2"]),
        user1_id=raw["user1_id"],
        user2_id=raw["user2_id"],
    )


@router.post("/duels/{duel_id}/predict", response_model=GenericResponse)
async def submit_prediction(predict_in: PredictionCreate, duel_id: uuid.UUID = Path(...)):
    """
    Submits a user's location prediction for their active duel.
    Validates that the submission occurs during the allowed guessing period.
    """
    duel_data = await _get_duel_or_404(duel_id)
    predictor_user = await _get_user_or_404(predict_in.username)
    predictor_id = predictor_user['id']
    now = datetime.now(timezone.utc)
    duel_date = datetime.fromisoformat(duel_data['duel_date'])

    if duel_data.get('status') != DuelStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duel is not active")

    # Determine opponent and their blackout
    opponent_id = None
    opponent_blackout = None
    predictor_field_lat = None
    predictor_field_lon = None

    if str(predictor_id) == duel_data['user1_id']:
        opponent_id = duel_data['user2_id']
        predictor_field_lat = "user1_predicted_lat"
        predictor_field_lon = "user1_predicted_lon"
        if duel_data.get(predictor_field_lat) is not None:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prediction already submitted for this user")
    elif str(predictor_id) == duel_data['user2_id']:
        opponent_id = duel_data['user1_id']
        predictor_field_lat = "user2_predicted_lat"
        predictor_field_lon = "user2_predicted_lon"
        if duel_data.get(predictor_field_lat) is not None:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prediction already submitted for this user")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not part of this duel")

    try:
        # Fetch opponent's blackout
        res_opp = await get_db().table("users").select("blackout_start_hour").eq("id", opponent_id).limit(1).execute()
        opponent_blackout = res_opp.data[0]['blackout_start_hour'] if res_opp.data else None

        # Validate prediction time using opponent's blackout
        if not utils.is_valid_prediction_time(now, opponent_blackout, duel_date):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prediction submitted outside the allowed time window")

        # Update prediction
        update_payload = {
            predictor_field_lat: predict_in.latitude,
            predictor_field_lon: predict_in.longitude
        }
        await get_db().table("duels").update(update_payload).eq("id", str(duel_id)).execute()

        return GenericResponse(message="Prediction submitted successfully")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error submitting prediction for duel {duel_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error submitting prediction")


@router.post("/duels/{duel_id}/checkin", response_model=GenericResponse)
async def submit_checkin(checkin_in: CheckinCreate, duel_id: uuid.UUID = Path(...)):
    """
    Submits a user's actual location at their snipe time.
    Validates that the submission occurs within the strict time window.
    Triggers result calculation if this is the final check-in needed.
    """
    duel_data = await _get_duel_or_404(duel_id)
    checkin_user = await _get_user_or_404(checkin_in.username)
    checkin_user_id = checkin_user['id']
    checkin_time = checkin_in.timestamp # Assuming already datetime object from model
    # Ensure check-in time is UTC
    if checkin_time.tzinfo is None:
        checkin_time = checkin_time.replace(tzinfo=timezone.utc) # Make aware if naive

    if duel_data.get('status') != DuelStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duel is not active")

    # Determine user role and snipe time
    user_role = None
    snipe_time_str = None
    actual_lat_field = None
    actual_lon_field = None
    other_user_checked_in = False

    if str(checkin_user_id) == duel_data['user1_id']:
        user_role = 1
        snipe_time_str = duel_data.get('snipe_time_user1')
        actual_lat_field = "user1_actual_lat"
        actual_lon_field = "user1_actual_lon"
        if duel_data.get(actual_lat_field) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Check-in already submitted for user 1")
        other_user_checked_in = duel_data.get('user2_actual_lat') is not None
    elif str(checkin_user_id) == duel_data['user2_id']:
        user_role = 2
        snipe_time_str = duel_data.get('snipe_time_user2')
        actual_lat_field = "user2_actual_lat"
        actual_lon_field = "user2_actual_lon"
        if duel_data.get(actual_lat_field) is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Check-in already submitted for user 2")
        other_user_checked_in = duel_data.get('user1_actual_lat') is not None
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not part of this duel")

    if not snipe_time_str:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Snipe time not set for this user in the duel")

    snipe_time = datetime.fromisoformat(snipe_time_str)

    # Validate check-in time window
    if not utils.is_valid_checkin_time(snipe_time, checkin_time):
        # Instead of raising error immediately, consider setting DQ flag later during calculation
        # For now, reject upfront
        print(f"Check-in time {checkin_time} invalid for snipe time {snipe_time}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Check-in submitted outside the allowed time window ({utils.CHECKIN_TOLERANCE_MINUTES} mins around snipe time)")

    try:
        # Update check-in location
        update_payload = {
            actual_lat_field: checkin_in.latitude,
            actual_lon_field: checkin_in.longitude
        }
        await get_db().table("duels").update(update_payload).eq("id", str(duel_id)).execute()
        print(f"User {user_role} checked in for duel {duel_id}")

        # --- Trigger Result Calculation ---
        # If the *other* user has already checked in, trigger calculation
        if other_user_checked_in:
             print(f"Both users checked in for duel {duel_id}. Triggering result calculation.")
             await _calculate_and_update_duel_results(duel_id) # Await if sync, or run in background if async
        else:
             print(f"User {user_role} checked in, waiting for other user in duel {duel_id}.")


        return GenericResponse(message="Check-in submitted successfully")

    except Exception as e:
        print(f"Error submitting check-in for duel {duel_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error submitting check-in")


@router.get("/duels/{duel_id}/results", response_model=DuelResult)
async def get_duel_results(duel_id: uuid.UUID = Path(...)):
    """
    Retrieves the final results of a duel (winner, distances, DQ status).
    """
    duel_data = await _get_duel_or_404(duel_id)

    if duel_data.get('status') != DuelStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Duel results are not yet available or duel not found")

    # Map the relevant fields to the DuelResult model
    return DuelResult(
        winner_user_id=duel_data.get('winner_user_id'),
        user1_dq=duel_data.get('user1_dq', False),
        user2_dq=duel_data.get('user2_dq', False),
        user1_final_distance=duel_data.get('user1_final_distance'),
        user2_final_distance=duel_data.get('user2_final_distance')
    )