import re
from flask import current_app


def normalize_session_time(session_time):
    """
    Normalize session time format to ensure consistent spacing
    Example: '12.00pm- 1.30pm' -> '12.00pm - 1.30pm'
    """
    if not session_time:
        return ""

    # Clean the string
    session_time = str(session_time).strip()

    # Fix spacing around hyphens
    session_time = re.sub(r'\s*-\s*', ' - ', session_time)

    return session_time


def get_default_session(day):
    """Get a default session with the most available capacity for the given day"""
    from models import Session
    
    # Get all sessions for this day
    sessions = Session.query.filter_by(day=day).all()
    
    # If no sessions exist yet, return None
    if not sessions:
        return None
    
    # Find session with most available capacity across both classrooms
    best_session = None
    most_available = -1
    
    for session in sessions:
        # Get counts for both classrooms
        laptop_count = get_session_count(session.id, current_app.config['LAPTOP_CLASSROOM'])
        no_laptop_count = get_session_count(session.id, current_app.config['NO_LAPTOP_CLASSROOM'])
        
        # Get capacities
        laptop_capacity = get_session_capacity(current_app.config['LAPTOP_CLASSROOM'])
        no_laptop_capacity = get_session_capacity(current_app.config['NO_LAPTOP_CLASSROOM'])
        
        # Calculate available seats
        laptop_available = laptop_capacity - laptop_count
        no_laptop_available = no_laptop_capacity - no_laptop_count
        total_available = laptop_available + no_laptop_available
        
        if total_available > most_available:
            most_available = total_available
            best_session = session
    
    return best_session


def is_valid_session_time(session_time, day=None):
    """
    Check if the session time is valid for the given day
    """
    normalized_time = normalize_session_time(session_time)

    if day == 'Saturday' or day is None:
        if normalized_time in current_app.config['SATURDAY_SESSIONS']:
            return True

    if day == 'Sunday' or day is None:
        if normalized_time in current_app.config['SUNDAY_SESSIONS']:
            return True

    return False


def get_session_by_time(session_time, day):
    """
    Get session object by time and day
    """
    from models import Session

    normalized_time = normalize_session_time(session_time)

    session = Session.query.filter_by(
        day=day,
        time_slot=normalized_time
    ).first()

    return session


def map_participants_to_sessions(participants, day):
    """
    Group participants by their session time for a specific day
    Returns: Dictionary where keys are session times and values are lists of participants
    """
    sessions_map = {}

    for participant in participants:
        if day == 'Saturday':
            session_time = participant.saturday_session.time_slot if participant.saturday_session else None
        else:
            session_time = participant.sunday_session.time_slot if participant.sunday_session else None

        if session_time:
            if session_time not in sessions_map:
                sessions_map[session_time] = []

            sessions_map[session_time].append(participant)

    return sessions_map


def get_participants_by_time_and_laptop(session_time, day, has_laptop=None):
    """
    Get participants for a specific session time and optionally filtered by laptop status
    """
    from models import Participant

    session = get_session_by_time(session_time, day)

    if not session:
        return []

    query = Participant.query

    if day == 'Saturday':
        query = query.filter(Participant.saturday_session_id == session.id)
    else:
        query = query.filter(Participant.sunday_session_id == session.id)

    if has_laptop is not None:
        query = query.filter(Participant.has_laptop == has_laptop)

    return query.all()


def get_session_capacity(classroom):
    """Get the capacity for a specific classroom"""
    capacities = current_app.config.get('SESSION_CAPACITY', {})
    return capacities.get(classroom, 30)  # Default to 30 if not specified


def get_session_count(session_id, classroom):
    """Get current count of participants in a session for a specific classroom"""
    from models import Participant

    # Count participants with this session who are in this classroom
    count_saturday = Participant.query.filter_by(
        saturday_session_id=session_id,
        classroom=classroom
    ).count()

    count_sunday = Participant.query.filter_by(
        sunday_session_id=session_id,
        classroom=classroom
    ).count()

    return max(count_saturday, count_sunday)  # Return the higher count


def is_session_available(session_id, classroom):
    """Check if a session has available capacity for the given classroom"""
    capacity = get_session_capacity(classroom)
    current_count = get_session_count(session_id, classroom)

    return current_count < capacity


def find_available_session(day, has_laptop, current_session_id=None):
    """
    Find an available session with capacity on the given day
    Returns: Session object or None if no available sessions
    """
    from models import Session

    # Get classroom based on laptop status
    classroom = current_app.config['LAPTOP_CLASSROOM'] if has_laptop else current_app.config['NO_LAPTOP_CLASSROOM']

    # Get all sessions for this day
    sessions = Session.query.filter_by(day=day).all()

    # If we have a current session ID, try to use that first
    if current_session_id:
        current_session = Session.query.get(current_session_id)
        if current_session and is_session_available(current_session.id, classroom):
            return current_session

    # Try each session in order
    for session in sessions:
        if is_session_available(session.id, classroom):
            return session

    # No available sessions found
    return None
