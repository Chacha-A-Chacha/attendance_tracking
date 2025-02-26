# services/verification.py
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from models import Participant, Session, Attendance
from app import db
from datetime import datetime
import calendar


class AttendanceVerifier:
    def __init__(self):
        self.today = datetime.now()

    def is_saturday(self):
        """Determine if today is Saturday (for testing purposes, can be overridden)"""
        return self.today.weekday() == 5  # 5 is Saturday

    def is_sunday(self):
        """Determine if today is Sunday (for testing purposes, can be overridden)"""
        return self.today.weekday() == 6  # 6 is Sunday

    def get_current_day_name(self):
        """Get the current day name"""
        return calendar.day_name[self.today.weekday()]

    def get_session_by_time(self, time_slot):
        """Get session object by time slot and current day"""
        day_name = "Saturday" if self.is_saturday() else "Sunday"

        # For testing purposes, if not weekend, use the day name parameter
        if not (self.is_saturday() or self.is_sunday()):
            # Default to showing an error in production, but for testing:
            current_app.logger.warning(f"Attendance verification on a {day_name}, using simulation mode")

        session = Session.query.filter_by(
            day=day_name,
            time_slot=time_slot
        ).first()

        return session

    def verify_attendance(self, unique_id, current_session_time):
        """Verify if participant is in correct session"""
        try:
            # Find the participant
            participant = Participant.query.filter_by(unique_id=unique_id).first()

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': 'participant_not_found'
                }

            # Get the session object for the current time
            current_session = self.get_session_by_time(current_session_time)

            if not current_session:
                return {
                    'success': False,
                    'message': f'Invalid session time: {current_session_time}',
                    'error_code': 'invalid_session'
                }

            # Determine expected session based on day
            if self.is_saturday():
                expected_session_id = participant.saturday_session_id
                expected_session = participant.saturday_session
            else:
                expected_session_id = participant.sunday_session_id
                expected_session = participant.sunday_session

            is_correct_session = (current_session.id == expected_session_id)

            # Record attendance regardless of whether it's the correct session
            attendance = Attendance(
                participant_id=participant.id,
                session_id=current_session.id,
                timestamp=self.today,
                is_correct_session=is_correct_session
            )

            db.session.add(attendance)
            db.session.commit()

            # Prepare response
            response = {
                'participant': {
                    'name': participant.name,
                    'email': participant.email,
                    'phone': participant.phone,
                    'classroom': participant.classroom,
                    'has_laptop': participant.has_laptop
                },
                'attendance_recorded': True,
                'timestamp': self.today.strftime('%Y-%m-%d %H:%M:%S')
            }

            if is_correct_session:
                response.update({
                    'success': True,
                    'message': 'Attendance verified. Participant is in the correct session.',
                    'status': 'correct_session'
                })
            else:
                # Add information about the correct session
                response.update({
                    'success': False,
                    'message': 'Participant is in the wrong session.',
                    'status': 'wrong_session',
                    'correct_session': {
                        'time': expected_session.time_slot if expected_session else 'Unknown',
                        'day': expected_session.day if expected_session else self.get_current_day_name()
                    }
                })

            return response

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error during attendance verification: {str(e)}")
            return {
                'success': False,
                'message': 'Database error occurred during verification',
                'error_code': 'database_error'
            }
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error during attendance verification: {str(e)}")
            return {
                'success': False,
                'message': 'An unexpected error occurred',
                'error_code': 'unknown_error'
            }

    def get_participant_attendance_history(self, unique_id):
        """Get attendance history for a participant"""
        participant = Participant.query.filter_by(unique_id=unique_id).first()

        if not participant:
            return {
                'success': False,
                'message': 'Participant not found',
                'error_code': 'participant_not_found'
            }

        # Get all attendance records for this participant
        attendance_records = Attendance.query.filter_by(
            participant_id=participant.id
        ).order_by(Attendance.timestamp.desc()).all()

        history = []
        for record in attendance_records:
            session = Session.query.get(record.session_id)
            history.append({
                'timestamp': record.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'session': session.time_slot if session else 'Unknown',
                'day': session.day if session else 'Unknown',
                'correct_session': record.is_correct_session
            })

        return {
            'success': True,
            'participant': {
                'name': participant.name,
                'email': participant.email,
                'classroom': participant.classroom
            },
            'attendance_history': history
        }
