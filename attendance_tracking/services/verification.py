from models.participant import Participant
from models.attendance import Attendance
from app import db
from datetime import datetime

def verify_attendance(unique_id, current_session):
    """Verify if participant is in correct session"""
    participant = Participant.query.filter_by(unique_id=unique_id).first()
    
    if not participant:
        return {
            'success': False,
            'message': 'Participant not found'
        }
    
    # Determine if we're checking Saturday or Sunday based on current time
    is_saturday = datetime.now().weekday() == 5  # 5 is Saturday
    expected_session = participant.saturday_session if is_saturday else participant.sunday_session
    
    is_correct_session = current_session == expected_session
    
    # Record attendance regardless
    attendance = Attendance(
        participant_id=participant.id,
        session=current_session,
        timestamp=datetime.now(),
        is_correct_session=is_correct_session
    )
    db.session.add(attendance)
    db.session.commit()
    
    if is_correct_session:
        return {
            'success': True,
            'message': 'Attendance verified',
            'participant': {
                'name': participant.name,
                'classroom': participant.classroom
            }
        }
    else:
        return {
            'success': False,
            'message': 'Incorrect session',
            'correct_session': expected_session,
            'participant': {
                'name': participant.name,
                'classroom': participant.classroom
            }
        }
    