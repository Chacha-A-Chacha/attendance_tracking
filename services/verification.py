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

    
    def mark_absent_participants(self, session_id):
        """Mark as absent all participants who were expected but not recorded for a session"""
        try:
            # Get the session
            session = Session.query.get(session_id)
            if not session:
                return {
                    'success': False,
                    'message': 'Session not found',
                    'error_code': 'session_not_found'
                }
                
            # Determine which day this is for
            is_saturday = session.day == 'Saturday'
            
            # Find all participants expected in this session
            if is_saturday:
                expected_participants = Participant.query.filter_by(saturday_session_id=session_id).all()
            else:
                expected_participants = Participant.query.filter_by(sunday_session_id=session_id).all()
                
            # Get all attendance records for this session
            attendance_records = Attendance.query.filter_by(session_id=session_id).all()
            
            # Get IDs of participants who already have attendance records
            recorded_participant_ids = [record.participant_id for record in attendance_records]
            
            # Find participants without attendance records
            absent_participants = [p for p in expected_participants if p.id not in recorded_participant_ids]
            
            # Mark these participants as absent
            for participant in absent_participants:
                # Create an absence record
                absence = Attendance(
                    participant_id=participant.id,
                    session_id=session_id,
                    timestamp=self.today,
                    is_correct_session=True,  # The session is correct, they're just absent
                    status='absent'  # Add a status field to the Attendance model
                )
                db.session.add(absence)
                
            db.session.commit()
            
            return {
                'success': True,
                'message': f'Marked {len(absent_participants)} participants as absent',
                'absent_count': len(absent_participants),
                'total_expected': len(expected_participants)
            }
                
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error marking absences: {str(e)}")
            return {
                'success': False,
                'message': 'Database error occurred',
                'error_code': 'database_error'
            }
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error marking absences: {str(e)}")
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
    

    def get_attendance_by_session(self, session_id, date=None, include_absent=True):
        """
        Get attendance records for a specific session on a specific date, organized by class
        
        Args:
            session_id: ID of the session to retrieve attendance for
            date: Date for which to retrieve attendance (datetime.date object or YYYY-MM-DD string)
                If None, uses the current date
            include_absent: Whether to include absent participants in the report
            
        Returns:
            Dictionary with attendance data and statistics
        """
        try:
            # Get the session
            session = Session.query.get(session_id)
            if not session:
                return {
                    'success': False,
                    'message': 'Session not found',
                    'error_code': 'session_not_found'
                }
                
            # Handle date parameter
            if date is None:
                # Use current date
                attendance_date = self.today.date()
            elif isinstance(date, str):
                # Parse string date in format YYYY-MM-DD
                try:
                    attendance_date = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    return {
                        'success': False,
                        'message': 'Invalid date format. Use YYYY-MM-DD',
                        'error_code': 'invalid_date_format'
                    }
            else:
                # Assume it's already a date object
                attendance_date = date
                
            # Verify the day of week matches the session day
            day_of_week = attendance_date.strftime("%A")
            if day_of_week != session.day:
                return {
                    'success': False,
                    'message': f'Date {attendance_date} is a {day_of_week}, not a {session.day}',
                    'error_code': 'day_mismatch'
                }
                
            # Determine if this is a Saturday or Sunday session
            is_saturday = session.day == 'Saturday'
            
            # Get all expected participants for this session
            if is_saturday:
                expected_participants = Participant.query.filter_by(saturday_session_id=session_id).all()
            else:
                expected_participants = Participant.query.filter_by(sunday_session_id=session_id).all()
                
            # Get all attendance records for this session on the specific date
            # Filter by both session_id and date
            attendance_records = Attendance.query.filter(
                Attendance.session_id == session_id,
                func.date(Attendance.timestamp) == attendance_date
            ).all()
            
            # Create a mapping of participant ID to attendance record
            attendance_map = {record.participant_id: record for record in attendance_records}
            
            # Organize participants by classroom
            classes = {}
            
            # Track statistics
            stats = {
                'total_expected': len(expected_participants),
                'total_present': 0,
                'total_absent': 0,
                'wrong_session': 0,
                'by_class': {}
            }
            
            # Process each expected participant
            for participant in expected_participants:
                # Get classroom and initialize if needed
                classroom = participant.classroom
                if classroom not in classes:
                    classes[classroom] = {
                        'present': [],
                        'absent': [],
                        'wrong_session': []
                    }
                    stats['by_class'][classroom] = {
                        'expected': 0,
                        'present': 0,
                        'absent': 0,
                        'wrong_session': 0
                    }
                
                stats['by_class'][classroom]['expected'] += 1
                
                # Check if participant has an attendance record
                if participant.id in attendance_map:
                    record = attendance_map[participant.id]
                    
                    # Check if they were in the correct session
                    if record.is_correct_session:
                        # Check if they were marked as present or absent
                        if getattr(record, 'status', 'present') == 'present':
                            classes[classroom]['present'].append({
                                'id': participant.id,
                                'unique_id': participant.unique_id,
                                'name': participant.name,
                                'email': participant.email,
                                'phone': participant.phone,
                                'has_laptop': participant.has_laptop,
                                'timestamp': record.timestamp.strftime('%H:%M:%S')
                            })
                            stats['total_present'] += 1
                            stats['by_class'][classroom]['present'] += 1
                        else:
                            # They were marked absent
                            classes[classroom]['absent'].append({
                                'id': participant.id,
                                'unique_id': participant.unique_id,
                                'name': participant.name,
                                'email': participant.email,
                                'phone': participant.phone,
                                'has_laptop': participant.has_laptop
                            })
                            stats['total_absent'] += 1
                            stats['by_class'][classroom]['absent'] += 1
                    else:
                        # They were in the wrong session
                        classes[classroom]['wrong_session'].append({
                            'id': participant.id,
                            'unique_id': participant.unique_id,
                            'name': participant.name,
                            'email': participant.email,
                            'phone': participant.phone,
                            'has_laptop': participant.has_laptop,
                            'timestamp': record.timestamp.strftime('%H:%M:%S')
                        })
                        stats['wrong_session'] += 1
                        stats['by_class'][classroom]['wrong_session'] += 1
                elif include_absent:
                    # No attendance record, so they're absent
                    classes[classroom]['absent'].append({
                        'id': participant.id,
                        'unique_id': participant.unique_id,
                        'name': participant.name,
                        'email': participant.email,
                        'phone': participant.phone,
                        'has_laptop': participant.has_laptop
                    })
                    stats['total_absent'] += 1
                    stats['by_class'][classroom]['absent'] += 1
            
            # Calculate attendance percentages
            if stats['total_expected'] > 0:
                stats['attendance_rate'] = round((stats['total_present'] / stats['total_expected']) * 100, 1)
                
                for classroom in stats['by_class']:
                    if stats['by_class'][classroom]['expected'] > 0:
                        stats['by_class'][classroom]['attendance_rate'] = round(
                            (stats['by_class'][classroom]['present'] / stats['by_class'][classroom]['expected']) * 100, 1
                        )
            
            return {
                'success': True,
                'session': {
                    'id': session.id,
                    'day': session.day,
                    'date': attendance_date.strftime('%Y-%m-%d'),
                    'time_slot': session.time_slot
                },
                'classes': classes,
                'stats': stats
            }
                
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error retrieving attendance: {str(e)}")
            return {
                'success': False,
                'message': 'Database error occurred',
                'error_code': 'database_error'
            }
        except Exception as e:
            current_app.logger.error(f"Unexpected error retrieving attendance: {str(e)}")
            return {
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}',
                'error_code': 'unknown_error'
            }
