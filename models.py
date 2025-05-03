import uuid
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

# Import field_validator instead of validator
from pydantic import BaseModel, Field, field_validator

# --- Enums ---

class DuelStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"

# --- Base Models / Common Structures ---

class GenericResponse(BaseModel):
    """Standard success/error message response."""
    message: str
    detail: Optional[str] = None

class Coordinate(BaseModel):
    """Represents geographical coordinates."""
    latitude: float = Field(..., ge=-90, le=90) # Latitude must be between -90 and 90
    longitude: float = Field(..., ge=-180, le=180) # Longitude must be between -180 and 180

# --- User Models ---

class UserBase(BaseModel):
    """Base user model with username."""
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9]+$") # Example validation

class UserCreate(UserBase):
    """Model for creating a new user (request body for POST /users/)."""
    pass # Only username needed

class UserPublic(UserBase):
    """Model for publicly accessible user data (e.g., response from user creation)."""
    id: uuid.UUID

    class Config:
        # Note: orm_mode is deprecated in Pydantic V2, use from_attributes=True
        from_attributes = True # Enable reading data from ORM objects/other attribute sources

class UserProfile(UserBase):
    """Model for user profile data (response for GET /users/{username})."""
    blackout_start_hour: Optional[int] = Field(None, ge=12, le=19) # Validate hour range

    class Config:
        from_attributes = True

class UserSettingsUpdate(BaseModel):
    """Model for updating user settings (request body for PUT /users/{username}/settings)."""
    # Allow explicit null to clear the setting
    blackout_start_hour: Optional[int] = Field(None) # Removed ge/le here, handled by validator

    # Use @field_validator instead of @validator
    @field_validator('blackout_start_hour')
    @classmethod # Validators should be class methods
    def validate_hour(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (12 <= v <= 19):
            raise ValueError('Blackout start hour must be between 12 and 19, or null')
        return v

class UserSearchResult(UserBase):
    """Model for user search results (response for GET /users/search)."""
    pass # Just username needed for search result

    class Config:
        from_attributes = True

# --- Friend Models ---

class Friend(UserBase):
    """Model representing a friend in the friends list (response for GET /users/{username}/friends)."""
    status: Optional[str] = None # e.g., "active_duel"

    class Config:
        from_attributes = True

class FriendRequest(BaseModel):
    """Model representing an incoming friend request (response for GET /users/{username}/friends/requests)."""
    request_id: uuid.UUID # The ID of the friendship record
    from_username: str

    class Config:
        from_attributes = True

class FriendRequestCreate(BaseModel):
    """Model for sending a friend request (request body for POST /friends/requests)."""
    from_username: str
    to_username: str

# --- Duel Models ---

class DuelBase(BaseModel):
    """Base model containing common duel fields."""
    id: uuid.UUID
    duel_date: date
    user1_id: uuid.UUID
    user2_id: uuid.UUID
    status: DuelStatus

class Duel(DuelBase):
    """Full duel details model (response for POST /duels/, POST /duels/{duel_id}/accept)."""
    snipe_time_user1: Optional[datetime] = None
    snipe_time_user2: Optional[datetime] = None
    user1_predicted_lat: Optional[float] = None
    user1_predicted_lon: Optional[float] = None
    user2_predicted_lat: Optional[float] = None
    user2_predicted_lon: Optional[float] = None
    user1_actual_lat: Optional[float] = None
    user1_actual_lon: Optional[float] = None
    user2_actual_lat: Optional[float] = None
    user2_actual_lon: Optional[float] = None
    user1_dq: bool = False
    user2_dq: bool = False
    user1_final_distance: Optional[float] = None
    user2_final_distance: Optional[float] = None
    winner_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Add opponent username for convenience in frontend if needed, requires backend logic
    # opponent_username: Optional[str] = None

    class Config:
        from_attributes = True
        use_enum_values = True # Serialize Enum members to their values (strings)

class DuelRequestCreate(BaseModel):
    """Model for requesting a new duel (request body for POST /duels/)."""
    requester_username: str
    opponent_username: str

class CurrentDuelInfo(BaseModel):
    """Model for the user's current active duel (response for GET /users/{username}/current)."""
    id: uuid.UUID
    opponent_username: str
    status: DuelStatus # Should always be ACTIVE if returned
    snipe_time_user1: Optional[datetime] = None # Return specific times relevant to the duel
    snipe_time_user2: Optional[datetime] = None
    user1_id: uuid.UUID # Include user IDs for potential frontend logic
    user2_id: uuid.UUID

    class Config:
        from_attributes = True
        use_enum_values = True

class PredictionCreate(Coordinate):
    """Model for submitting a prediction (request body for POST /duels/{duel_id}/predict)."""
    username: str

class CheckinCreate(Coordinate):
    """Model for submitting a check-in (request body for POST /duels/{duel_id}/checkin)."""
    username: str
    timestamp: datetime # Expecting ISO 8601 format string from client

class DuelResult(BaseModel):
    """Model for duel results (response for GET /duels/{duel_id}/results)."""
    winner_user_id: Optional[uuid.UUID] = None
    user1_dq: bool
    user2_dq: bool
    user1_final_distance: Optional[float] = None
    user2_final_distance: Optional[float] = None

    # Optional: Add usernames for clarity if backend joins them
    # user1_username: Optional[str] = None
    # user2_username: Optional[str] = None

    class Config:
        from_attributes = True
        
class DuelRequest(BaseModel):
    """Model for duel requests (response for GET /duels/requests)."""
    id: uuid.UUID
    requester_username: str
    created_at: datetime
    
    class Config:
        from_attributes = True