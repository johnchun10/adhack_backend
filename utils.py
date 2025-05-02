import uuid
import math
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple

# --- Constants ---
# Define duel activity window (local time, assuming server runs in UTC or consistent timezone)
# For simplicity, let's define these as naive time objects first
DUEL_START_HOUR_LOCAL = 12 # 12 PM
DUEL_END_HOUR_LOCAL = 0 # 12 AM (next day) - Be careful with date rollovers

# Time window around snipe time for valid check-in (e.g., +/- 2 minutes)
CHECKIN_TOLERANCE_MINUTES = 2


# --- Time Utilities ---

def get_today_utc() -> date:
    """Gets the current date in UTC."""
    return datetime.now(timezone.utc).date()

def calculate_blackout_window_utc(
    blackout_start_hour_local: Optional[int], # Hour (12-19) in user's local time perception
    reference_date_utc: date
) -> Optional[Tuple[datetime, datetime]]:
    """
    Calculates the UTC start and end times for a user's blackout window
    on a specific UTC date.
    """
    if blackout_start_hour_local is None or not (12 <= blackout_start_hour_local <= 19):
        return None

    # Assume blackout_start_hour is specified relative to the duel day's local time.
    # For backend logic, it's often simpler to work entirely in UTC.
    # We'll define the window based on the reference UTC date.
    # NOTE: This simplification assumes the 'local' start hour maps directly
    # to the same hour number on the UTC date. Timezone differences could make
    # this complex. If precision across timezones is critical, store user timezone
    # and perform timezone conversions. For now, we assume direct mapping.

    try:
        start_dt_utc = datetime.combine(reference_date_utc, time(hour=blackout_start_hour_local), tzinfo=timezone.utc)
        # Blackout lasts 5 hours
        end_dt_utc = start_dt_utc + timedelta(hours=5)
        return start_dt_utc, end_dt_utc
    except ValueError:
        # Handles cases like invalid hour combination
        return None

def generate_random_snipe_time_utc(
    target_user_blackout_start_hour: Optional[int], # Opponent's blackout start
    reference_date_utc: date
) -> datetime:
    """
    Generates a random snipe time within the allowed window (12 PM - 12 AM local equivalent)
    for a specific UTC date, excluding the target user's blackout period.
    """

    # Define the overall duel activity window in UTC for the reference date
    # Again, assumes direct mapping of local 12 PM to 12:00 UTC for simplicity.
    # Adjust if server timezone or user timezones are handled differently.
    try:
        duel_window_start_utc = datetime.combine(reference_date_utc, time(hour=DUEL_START_HOUR_LOCAL), tzinfo=timezone.utc)
        # Duel window ends at 12 AM *the next day* UTC relative to the start hour mapping
        # This needs careful handling if DUEL_END_HOUR_LOCAL is 0
        duel_window_end_utc = datetime.combine(reference_date_utc + timedelta(days=1), time(hour=DUEL_END_HOUR_LOCAL), tzinfo=timezone.utc)
        # Total duration: 12 hours in seconds
        total_window_seconds = int((duel_window_end_utc - duel_window_start_utc).total_seconds())

    except ValueError:
        # Fallback if time combination fails (shouldn't with constants)
        raise ValueError("Could not define base duel window UTC times.")


    # Calculate the target user's blackout window in UTC
    blackout_window = calculate_blackout_window_utc(target_user_blackout_start_hour, reference_date_utc)

    valid_intervals_seconds = [] # List of tuples: (start_offset, end_offset) in seconds from duel_window_start_utc

    if blackout_window:
        blackout_start_utc, blackout_end_utc = blackout_window

        # Ensure blackout times are within the reference date context if needed, though UTC handles this
        # Clamp blackout times to be within the overall duel window
        effective_blackout_start = max(duel_window_start_utc, blackout_start_utc)
        effective_blackout_end = min(duel_window_end_utc, blackout_end_utc)

        # Calculate valid intervals relative to the start of the duel window
        # Interval 1: From duel start to blackout start (if blackout doesn't start before/at duel start)
        if effective_blackout_start > duel_window_start_utc:
            start_offset = 0
            end_offset = int((effective_blackout_start - duel_window_start_utc).total_seconds())
            if end_offset > start_offset:
                 valid_intervals_seconds.append((start_offset, end_offset))

        # Interval 2: From blackout end to duel end (if blackout doesn't end after/at duel end)
        if effective_blackout_end < duel_window_end_utc:
            start_offset = int((effective_blackout_end - duel_window_start_utc).total_seconds())
            end_offset = total_window_seconds
            if end_offset > start_offset:
                 valid_intervals_seconds.append((start_offset, end_offset))
    else:
        # No blackout, the entire window is valid
        valid_intervals_seconds.append((0, total_window_seconds))

    if not valid_intervals_seconds:
        # Should not happen unless blackout covers the entire 12h window
        raise ValueError("No valid time intervals found for snipe time generation.")

    # Calculate total duration of valid intervals
    total_valid_seconds = sum(end - start for start, end in valid_intervals_seconds)

    if total_valid_seconds <= 0:
        raise ValueError("Total valid seconds for snipe time is zero or negative.")

    # Choose a random second within the total valid duration
    random_second_offset_overall = random.randrange(total_valid_seconds)

    # Find which interval this random second falls into and calculate the final offset
    cumulative_seconds = 0
    final_offset_in_window = 0
    for start, end in valid_intervals_seconds:
        duration = end - start
        if random_second_offset_overall < cumulative_seconds + duration:
            offset_within_interval = random_second_offset_overall - cumulative_seconds
            final_offset_in_window = start + offset_within_interval
            break
        cumulative_seconds += duration

    # Calculate the final snipe time
    snipe_time_utc = duel_window_start_utc + timedelta(seconds=final_offset_in_window)

    return snipe_time_utc


def is_valid_checkin_time(
    snipe_time_utc: datetime,
    checkin_time_utc: datetime,
    tolerance_minutes: int = CHECKIN_TOLERANCE_MINUTES
) -> bool:
    """
    Checks if the check-in time is within the allowed tolerance window
    around the snipe time.
    """
    if not snipe_time_utc or not checkin_time_utc:
        return False # Cannot validate without both times

    # Ensure times are timezone-aware (UTC)
    if snipe_time_utc.tzinfo is None or snipe_time_utc.tzinfo.utcoffset(snipe_time_utc) != timedelta(0):
         raise ValueError("snipe_time_utc must be timezone-aware UTC")
    if checkin_time_utc.tzinfo is None or checkin_time_utc.tzinfo.utcoffset(checkin_time_utc) != timedelta(0):
         raise ValueError("checkin_time_utc must be timezone-aware UTC")


    lower_bound = snipe_time_utc - timedelta(minutes=tolerance_minutes)
    upper_bound = snipe_time_utc + timedelta(minutes=tolerance_minutes)

    return lower_bound <= checkin_time_utc <= upper_bound


def is_valid_prediction_time(
    current_time_utc: datetime,
    opponent_blackout_start_hour: Optional[int], # Opponent's blackout start
    reference_date_utc: date
) -> bool:
    """
    Checks if the current time is a valid time to make a prediction for a duel
    on the given reference date. Prediction is allowed anytime EXCEPT during
    the opponent's active duel window (12PM-12AM) unless it's their blackout period.
    """
     # Ensure current time is timezone-aware UTC
    if current_time_utc.tzinfo is None or current_time_utc.tzinfo.utcoffset(current_time_utc) != timedelta(0):
         raise ValueError("current_time_utc must be timezone-aware UTC")

    # Define the opponent's overall duel activity window in UTC for the reference date
    try:
        duel_window_start_utc = datetime.combine(reference_date_utc, time(hour=DUEL_START_HOUR_LOCAL), tzinfo=timezone.utc)
        duel_window_end_utc = datetime.combine(reference_date_utc + timedelta(days=1), time(hour=DUEL_END_HOUR_LOCAL), tzinfo=timezone.utc)
    except ValueError:
        return False # Cannot determine window

    # --- Check 1: Is the current time outside the 12 PM - 12 AM window entirely? ---
    # If yes, prediction IS allowed.
    if current_time_utc < duel_window_start_utc or current_time_utc >= duel_window_end_utc:
        return True

    # --- Check 2: It's *inside* the 12 PM - 12 AM window. Is it during opponent's blackout? ---
    blackout_window = calculate_blackout_window_utc(opponent_blackout_start_hour, reference_date_utc)

    if blackout_window:
        blackout_start_utc, blackout_end_utc = blackout_window
        # If current time is within the blackout period, prediction IS allowed.
        if blackout_start_utc <= current_time_utc < blackout_end_utc:
            return True

    # --- Check 3: It's inside 12 PM - 12 AM window AND *not* during opponent's blackout ---
    # Therefore, prediction is NOT allowed.
    return False


# --- Location Utilities ---

def calculate_haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Calculates the distance between two points on Earth using the Haversine formula.
    """
    R = 6371000  # Radius of Earth in meters

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance

# --- Other Potential Utilities (Add as needed) ---
# E.g., function to get user ID from username if frequently needed and not part of a dedicated service
# def get_user_id_from_username(db_client, username: str) -> Optional[uuid.UUID]: ...