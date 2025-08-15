# services/attendance_service.py
"""
Comprehensive Attendance Management Service.
Handles attendance verification, recording, reporting, and analytics with optimized database operations.
Integrates with existing model methods and service architecture.
"""

import logging
from datetime import datetime, timedelta, date
from flask import current_app
from sqlalchemy import and_, or_, func, exists, case, text, desc
from sqlalchemy.orm import joinedload, selectinload, contains_eager
from sqlalchemy.exc import IntegrityError

from app.models.attendance import Attendance
from app.models.participant import Participant
from app.models.session import Session
from app.models.user import User
from app.extensions import db, email_service
from app.utils.enhanced_email import Priority


class AttendanceError:
    """Attendance-specific error codes."""
    PARTICIPANT_NOT_FOUND = 'participant_not_found'
    SESSION_NOT_FOUND = 'session_not_found'
    DUPLICATE_ATTENDANCE = 'duplicate_attendance'
    WRONG_SESSION = 'wrong_session'
    INACTIVE_PARTICIPANT = 'inactive_participant'
    SESSION_NOT_ACTIVE = 'session_not_active'
    INVALID_SESSION_TIME = 'invalid_session_time'
    DAY_MISMATCH = 'day_mismatch'
    DATABASE_ERROR = 'database_error'
    PERMISSION_DENIED = 'permission_denied'


class AttendanceService:
    """Optimized service class for attendance management operations."""

    @staticmethod
    def verify_and_record_attendance(unique_id, session_identifier, check_in_method='qr_code',
                                     admin_user_id=None, force_record=False):
        """
        Verify and record participant attendance with comprehensive validation and optimization.

        Args:
            unique_id: Participant unique identifier
            session_identifier: Session time slot string or session ID
            check_in_method: 'qr_code', 'manual', 'bulk'
            admin_user_id: Admin user ID for manual check-ins
            force_record: Override duplicate check for admin corrections

        Returns:
            dict: Comprehensive response with participant info, attendance status, warnings
        """
        logger = logging.getLogger('attendance_service')

        try:
            # 1. Get participant with optimized eager loading
            participant = (
                db.session.query(Participant)
                .options(
                    joinedload(Participant.saturday_session),
                    joinedload(Participant.sunday_session),
                    joinedload(Participant.user)
                )
                .filter_by(unique_id=unique_id)
                .first()
            )

            if not participant:
                logger.warning(f"Attendance verification failed: Participant {unique_id} not found")
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': AttendanceError.PARTICIPANT_NOT_FOUND,
                    'unique_id': unique_id
                }

            # Check if participant is active
            if participant.user and not participant.user.is_active:
                logger.warning(f"Attendance verification failed: Participant {unique_id} is inactive")
                return {
                    'success': False,
                    'message': 'Participant account is inactive',
                    'error_code': AttendanceError.INACTIVE_PARTICIPANT,
                    'participant': AttendanceService._format_participant_info(participant)
                }

            # 2. Determine current session
            current_session, day_name = AttendanceService._resolve_session(session_identifier)

            if not current_session:
                logger.warning(f"Session resolution failed for identifier: {session_identifier}")
                return {
                    'success': False,
                    'message': f'Invalid session: {session_identifier}',
                    'error_code': AttendanceError.SESSION_NOT_FOUND,
                    'participant': AttendanceService._format_participant_info(participant)
                }

            # 3. Determine expected session and correctness
            is_saturday = day_name == 'Saturday'
            expected_session_id = (
                participant.saturday_session_id if is_saturday
                else participant.sunday_session_id
            )
            expected_session = (
                participant.saturday_session if is_saturday
                else participant.sunday_session
            )

            is_correct_session = (current_session.id == expected_session_id)

            # 4. Check for duplicate attendance (optimized query)
            attendance_date = datetime.now().date()
            existing_attendance = (
                db.session.query(Attendance)
                .filter(
                    and_(
                        Attendance.participant_id == participant.id,
                        Attendance.session_id == current_session.id,
                        func.date(Attendance.timestamp) == attendance_date
                    )
                )
                .first()
            )

            # Prepare base response
            response = {
                'participant': AttendanceService._format_participant_info(participant),
                'session': {
                    'id': current_session.id,
                    'time_slot': current_session.time_slot,
                    'day': current_session.day
                },
                'timestamp': datetime.now().isoformat(),
                'is_correct_session': is_correct_session,
                'check_in_method': check_in_method
            }

            # Handle existing attendance
            if existing_attendance and not force_record:
                logger.info(
                    f"Duplicate attendance attempt: {unique_id} already recorded for session {current_session.id}")
                response.update({
                    'success': True,
                    'attendance_recorded': False,
                    'message': f'Attendance already recorded at {existing_attendance.timestamp.strftime("%H:%M:%S")}',
                    'status': 'already_recorded',
                    'existing_attendance': {
                        'timestamp': existing_attendance.timestamp.isoformat(),
                        'is_correct_session': existing_attendance.is_correct_session,
                        'status': existing_attendance.status
                    }
                })

                # Add correct session info if wrong session
                if not existing_attendance.is_correct_session and expected_session:
                    response['expected_session'] = {
                        'id': expected_session.id,
                        'time_slot': expected_session.time_slot,
                        'day': expected_session.day
                    }

                return response

            # 5. Create new attendance record using model method
            attendance = Attendance(
                participant_id=participant.id,
                session_id=current_session.id,
                timestamp=datetime.now(),
                is_correct_session=is_correct_session,
                status='present',  # Default to present for check-ins
                check_in_method=check_in_method
            )

            # Use model's save method which handles participant tracking updates
            attendance.save()

            # 6. Send notifications for wrong session attendance
            if not is_correct_session:
                try:
                    AttendanceService._send_wrong_session_notification(
                        participant, current_session, expected_session
                    )
                except Exception as e:
                    logger.warning(f"Failed to send wrong session notification: {e}")

            # 7. Update response with successful attendance
            response.update({
                'success': True,
                'attendance_recorded': True,
                'attendance_id': attendance.id
            })

            if is_correct_session:
                response.update({
                    'message': 'Attendance verified successfully. Participant is in correct session.',
                    'status': 'correct_session'
                })
                logger.info(f"Correct session attendance: {unique_id} in {current_session.time_slot}")
            else:
                response.update({
                    'message': 'Attendance recorded but participant is in wrong session.',
                    'status': 'wrong_session',
                    'expected_session': {
                        'id': expected_session.id if expected_session else None,
                        'time_slot': expected_session.time_slot if expected_session else 'Unknown',
                        'day': expected_session.day if expected_session else day_name
                    }
                })
                logger.warning(
                    f"Wrong session attendance: {unique_id} in {current_session.time_slot}, expected {expected_session.time_slot if expected_session else 'Unknown'}")

            return response

        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Database integrity error during attendance verification: {str(e)}")
            return {
                'success': False,
                'message': 'Attendance record could not be created due to data conflict',
                'error_code': AttendanceError.DATABASE_ERROR
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Unexpected error during attendance verification: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'An unexpected error occurred during attendance verification',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def get_session_attendance_report(session_id, attendance_date=None, include_statistics=True,
                                      group_by_classroom=True):
        """
        Generate comprehensive session attendance report with optimized queries.

        Args:
            session_id: Session ID to report on
            attendance_date: Date for report (defaults to today)
            include_statistics: Include attendance statistics
            group_by_classroom: Group results by classroom

        Returns:
            dict: Detailed attendance report with statistics
        """
        logger = logging.getLogger('attendance_service')

        try:
            # Validate session
            session = db.session.query(Session).filter_by(id=session_id).first()
            if not session:
                return {
                    'success': False,
                    'message': 'Session not found',
                    'error_code': AttendanceError.SESSION_NOT_FOUND
                }

            # Handle date parameter
            if attendance_date is None:
                attendance_date = datetime.now().date()
            elif isinstance(attendance_date, str):
                try:
                    attendance_date = datetime.strptime(attendance_date, "%Y-%m-%d").date()
                except ValueError:
                    return {
                        'success': False,
                        'message': 'Invalid date format. Use YYYY-MM-DD',
                        'error_code': AttendanceError.INVALID_SESSION_TIME
                    }

            # Validate day matches session day
            day_of_week = attendance_date.strftime("%A")
            if day_of_week != session.day:
                return {
                    'success': False,
                    'message': f'Date {attendance_date} is a {day_of_week}, not a {session.day}',
                    'error_code': AttendanceError.DAY_MISMATCH
                }

            # Determine session type for participant lookup
            is_saturday = session.day == 'Saturday'

            # Get expected participants with optimized query
            expected_participants_query = (
                db.session.query(Participant)
                .options(joinedload(Participant.user))
            )

            if is_saturday:
                expected_participants = expected_participants_query.filter_by(
                    saturday_session_id=session_id
                ).all()
            else:
                expected_participants = expected_participants_query.filter_by(
                    sunday_session_id=session_id
                ).all()

            # Get attendance records with optimized query
            attendance_records = (
                db.session.query(Attendance)
                .options(joinedload(Attendance.participant))
                .filter(
                    and_(
                        Attendance.session_id == session_id,
                        func.date(Attendance.timestamp) == attendance_date
                    )
                )
                .all()
            )

            # Create attendance lookup map
            attendance_map = {record.participant_id: record for record in attendance_records}

            # Initialize result structure
            result = {
                'success': True,
                'session': {
                    'id': session.id,
                    'day': session.day,
                    'time_slot': session.time_slot,
                    'date': attendance_date.strftime('%Y-%m-%d')
                },
                'generated_at': datetime.now().isoformat()
            }

            # Organize participants by classroom or as single group
            if group_by_classroom:
                classrooms = {}
                stats_by_classroom = {}
            else:
                all_participants = {'present': [], 'absent': [], 'wrong_session': []}

            # Global statistics
            global_stats = {
                'total_expected': len(expected_participants),
                'total_present': 0,
                'total_absent': 0,
                'wrong_session_count': 0
            }

            # Process each expected participant
            for participant in expected_participants:
                participant_data = {
                    'id': participant.id,
                    'unique_id': participant.unique_id,
                    'full_name': participant.full_name,
                    'email': participant.email,
                    'phone': participant.phone,
                    'has_laptop': participant.has_laptop,
                    'classroom': participant.classroom
                }

                # Initialize classroom if needed
                if group_by_classroom:
                    classroom = participant.classroom
                    if classroom not in classrooms:
                        classrooms[classroom] = {'present': [], 'absent': [], 'wrong_session': []}
                        stats_by_classroom[classroom] = {
                            'expected': 0, 'present': 0, 'absent': 0, 'wrong_session': 0
                        }
                    stats_by_classroom[classroom]['expected'] += 1

                # Check attendance status
                if participant.id in attendance_map:
                    record = attendance_map[participant.id]
                    participant_data['attendance_timestamp'] = record.timestamp.strftime('%H:%M:%S')
                    participant_data['attendance_status'] = record.status

                    if record.is_correct_session and record.status == 'present':
                        # Present and correct session
                        target_list = classrooms[classroom]['present'] if group_by_classroom else all_participants[
                            'present']
                        target_list.append(participant_data)
                        global_stats['total_present'] += 1
                        if group_by_classroom:
                            stats_by_classroom[classroom]['present'] += 1

                    elif record.is_correct_session and record.status == 'absent':
                        # Marked absent but in correct session
                        target_list = classrooms[classroom]['absent'] if group_by_classroom else all_participants[
                            'absent']
                        target_list.append(participant_data)
                        global_stats['total_absent'] += 1
                        if group_by_classroom:
                            stats_by_classroom[classroom]['absent'] += 1

                    else:
                        # Wrong session
                        target_list = classrooms[classroom]['wrong_session'] if group_by_classroom else \
                        all_participants['wrong_session']
                        target_list.append(participant_data)
                        global_stats['wrong_session_count'] += 1
                        if group_by_classroom:
                            stats_by_classroom[classroom]['wrong_session'] += 1

                else:
                    # No attendance record - absent
                    target_list = classrooms[classroom]['absent'] if group_by_classroom else all_participants['absent']
                    target_list.append(participant_data)
                    global_stats['total_absent'] += 1
                    if group_by_classroom:
                        stats_by_classroom[classroom]['absent'] += 1

            # Add organized data to result
            if group_by_classroom:
                result['classrooms'] = classrooms
                if include_statistics:
                    result['classroom_statistics'] = stats_by_classroom
            else:
                result['participants'] = all_participants

            # Add global statistics
            if include_statistics:
                if global_stats['total_expected'] > 0:
                    global_stats['attendance_rate'] = round(
                        (global_stats['total_present'] / global_stats['total_expected']) * 100, 1
                    )
                else:
                    global_stats['attendance_rate'] = 0

                result['statistics'] = global_stats

                # Add classroom-level attendance rates
                if group_by_classroom:
                    for classroom in stats_by_classroom:
                        classroom_stats = stats_by_classroom[classroom]
                        if classroom_stats['expected'] > 0:
                            classroom_stats['attendance_rate'] = round(
                                (classroom_stats['present'] / classroom_stats['expected']) * 100, 1
                            )

            logger.info(f"Generated attendance report for session {session_id} on {attendance_date}")
            return result

        except Exception as e:
            logger.error(f"Error generating attendance report: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to generate attendance report',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def get_participant_attendance_summary(participant_id, date_range=None, include_sessions=True):
        """
        Get comprehensive attendance summary for a participant with optimized queries.

        Args:
            participant_id: Participant unique ID
            date_range: Tuple of (start_date, end_date) or None for all time
            include_sessions: Include detailed session information

        Returns:
            dict: Detailed attendance summary
        """
        logger = logging.getLogger('attendance_service')

        try:
            # Get participant with session information
            participant = (
                db.session.query(Participant)
                .options(
                    joinedload(Participant.saturday_session),
                    joinedload(Participant.sunday_session),
                    joinedload(Participant.user)
                )
                .filter_by(unique_id=participant_id)
                .first()
            )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': AttendanceError.PARTICIPANT_NOT_FOUND
                }

            # Build attendance query with optimizations
            attendance_query = (
                db.session.query(Attendance)
                .options(joinedload(Attendance.session))
                .filter_by(participant_id=participant.id)
            )

            # Apply date range filter if provided
            if date_range:
                start_date, end_date = date_range
                attendance_query = attendance_query.filter(
                    and_(
                        func.date(Attendance.timestamp) >= start_date,
                        func.date(Attendance.timestamp) <= end_date
                    )
                )

            # Get attendance records ordered by most recent
            attendance_records = attendance_query.order_by(desc(Attendance.timestamp)).all()

            # Calculate statistics using database aggregation
            stats_query = (
                db.session.query(
                    func.count(Attendance.id).label('total_sessions'),
                    func.sum(case((Attendance.is_correct_session == True, 1), else_=0)).label('correct_sessions'),
                    func.sum(case((Attendance.status == 'present', 1), else_=0)).label('present_sessions'),
                    func.sum(case((and_(Attendance.is_correct_session == True, Attendance.status == 'present'), 1),
                                  else_=0)).label('correct_and_present')
                )
                .filter_by(participant_id=participant.id)
            )

            if date_range:
                start_date, end_date = date_range
                stats_query = stats_query.filter(
                    and_(
                        func.date(Attendance.timestamp) >= start_date,
                        func.date(Attendance.timestamp) <= end_date
                    )
                )

            stats_result = stats_query.first()

            # Prepare response
            result = {
                'success': True,
                'participant': AttendanceService._format_participant_info(participant),
                'summary_period': {
                    'start_date': date_range[0].strftime('%Y-%m-%d') if date_range else None,
                    'end_date': date_range[1].strftime('%Y-%m-%d') if date_range else None,
                    'total_days': (date_range[1] - date_range[0]).days + 1 if date_range else None
                },
                'statistics': {
                    'total_sessions_attended': stats_result.total_sessions or 0,
                    'correct_sessions': stats_result.correct_sessions or 0,
                    'present_sessions': stats_result.present_sessions or 0,
                    'correct_and_present': stats_result.correct_and_present or 0,
                    'wrong_sessions': (stats_result.total_sessions or 0) - (stats_result.correct_sessions or 0),
                    'consecutive_missed_sessions': participant.consecutive_missed_sessions
                }
            }

            # Calculate percentages
            total = result['statistics']['total_sessions_attended']
            if total > 0:
                result['statistics']['correct_session_rate'] = round(
                    (result['statistics']['correct_sessions'] / total) * 100, 1
                )
                result['statistics']['attendance_rate'] = round(
                    (result['statistics']['present_sessions'] / total) * 100, 1
                )
            else:
                result['statistics']['correct_session_rate'] = 0
                result['statistics']['attendance_rate'] = 0

            # Include detailed session history if requested
            if include_sessions:
                session_history = []
                for record in attendance_records:
                    session_data = {
                        'attendance_id': record.id,
                        'date': record.timestamp.strftime('%Y-%m-%d'),
                        'time': record.timestamp.strftime('%H:%M:%S'),
                        'session': {
                            'id': record.session.id,
                            'time_slot': record.session.time_slot,
                            'day': record.session.day
                        },
                        'is_correct_session': record.is_correct_session,
                        'status': record.status,
                        'check_in_method': record.check_in_method
                    }
                    session_history.append(session_data)

                result['session_history'] = session_history

            logger.info(f"Generated attendance summary for participant {participant_id}")
            return result

        except Exception as e:
            logger.error(f"Error generating participant attendance summary: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to generate attendance summary',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def bulk_mark_absences(session_id, attendance_date=None, admin_user_id=None,
                           exclude_existing=True):
        """
        Mark all expected participants as absent if they haven't checked in.

        Args:
            session_id: Session ID to process
            attendance_date: Date to mark absences for (defaults to today)
            admin_user_id: Admin user performing the operation
            exclude_existing: Skip participants who already have attendance records

        Returns:
            dict: Results of bulk absence marking
        """
        logger = logging.getLogger('attendance_service')

        try:
            # Validate session
            session = db.session.query(Session).filter_by(id=session_id).first()
            if not session:
                return {
                    'success': False,
                    'message': 'Session not found',
                    'error_code': AttendanceError.SESSION_NOT_FOUND
                }

            # Handle date
            if attendance_date is None:
                attendance_date = datetime.now().date()
            elif isinstance(attendance_date, str):
                attendance_date = datetime.strptime(attendance_date, "%Y-%m-%d").date()

            # Get expected participants
            is_saturday = session.day == 'Saturday'
            if is_saturday:
                expected_participants = (
                    db.session.query(Participant)
                    .filter_by(saturday_session_id=session_id)
                    .all()
                )
            else:
                expected_participants = (
                    db.session.query(Participant)
                    .filter_by(sunday_session_id=session_id)
                    .all()
                )

            # Get existing attendance records for this session and date
            if exclude_existing:
                existing_participant_ids = (
                    db.session.query(Attendance.participant_id)
                    .filter(
                        and_(
                            Attendance.session_id == session_id,
                            func.date(Attendance.timestamp) == attendance_date
                        )
                    )
                    .all()
                )
                existing_ids = [row[0] for row in existing_participant_ids]

                # Filter out participants who already have records
                participants_to_mark = [
                    p for p in expected_participants
                    if p.id not in existing_ids
                ]
            else:
                participants_to_mark = expected_participants

            # Create absence records
            absence_records = []
            for participant in participants_to_mark:
                absence = Attendance(
                    participant_id=participant.id,
                    session_id=session_id,
                    timestamp=datetime.combine(attendance_date, datetime.now().time()),
                    is_correct_session=True,  # Correct session, they're just absent
                    status='absent',
                    check_in_method='bulk'
                )
                absence_records.append(absence)

            # Bulk insert using session.add_all for efficiency
            if absence_records:
                db.session.add_all(absence_records)

                # Update consecutive missed sessions for each participant
                for participant in participants_to_mark:
                    participant.record_attendance(session_id, is_present=False)

                db.session.commit()

            result = {
                'success': True,
                'message': f'Marked {len(absence_records)} participants as absent',
                'session': {
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'day': session.day,
                    'date': attendance_date.strftime('%Y-%m-%d')
                },
                'statistics': {
                    'total_expected': len(expected_participants),
                    'already_recorded': len(expected_participants) - len(participants_to_mark),
                    'marked_absent': len(absence_records)
                },
                'admin_user_id': admin_user_id
            }

            logger.info(
                f"Bulk absence marking completed for session {session_id}: {len(absence_records)} participants marked absent")
            return result

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during bulk absence marking: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to mark bulk absences',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def manual_attendance_override(participant_id, session_id, status, admin_user_id,
                                   attendance_date=None, notes=None):
        """
        Manual attendance override by admin users.

        Args:
            participant_id: Participant unique ID
            session_id: Session ID
            status: 'present', 'absent', 'late'
            admin_user_id: Admin user making the change
            attendance_date: Date for attendance (defaults to today)
            notes: Optional notes about the override

        Returns:
            dict: Result of manual override
        """
        logger = logging.getLogger('attendance_service')

        try:
            # Validate admin permissions
            admin_user = db.session.query(User).filter_by(id=admin_user_id).first()
            if not admin_user or not admin_user.is_staff():
                return {
                    'success': False,
                    'message': 'Insufficient permissions for manual attendance override',
                    'error_code': AttendanceError.PERMISSION_DENIED
                }

            # Get participant
            participant = (
                db.session.query(Participant)
                .filter_by(unique_id=participant_id)
                .first()
            )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': AttendanceError.PARTICIPANT_NOT_FOUND
                }

            # Get session
            session = db.session.query(Session).filter_by(id=session_id).first()
            if not session:
                return {
                    'success': False,
                    'message': 'Session not found',
                    'error_code': AttendanceError.SESSION_NOT_FOUND
                }

            # Handle date
            if attendance_date is None:
                attendance_date = datetime.now().date()
            elif isinstance(attendance_date, str):
                attendance_date = datetime.strptime(attendance_date, "%Y-%m-%d").date()

            # Check for existing attendance record
            existing_attendance = (
                db.session.query(Attendance)
                .filter(
                    and_(
                        Attendance.participant_id == participant.id,
                        Attendance.session_id == session_id,
                        func.date(Attendance.timestamp) == attendance_date
                    )
                )
                .first()
            )

            # Determine if this is correct session
            is_saturday = session.day == 'Saturday'
            expected_session_id = (
                participant.saturday_session_id if is_saturday
                else participant.sunday_session_id
            )
            is_correct_session = (session_id == expected_session_id)

            if existing_attendance:
                # Update existing record
                existing_attendance.status = status
                existing_attendance.check_in_method = 'manual_override'
                action = 'updated'
            else:
                # Create new record
                attendance = Attendance(
                    participant_id=participant.id,
                    session_id=session_id,
                    timestamp=datetime.combine(attendance_date, datetime.now().time()),
                    is_correct_session=is_correct_session,
                    status=status,
                    check_in_method='manual_override'
                )
                db.session.add(attendance)
                action = 'created'

            # Update participant attendance tracking
            is_present = status in ['present', 'late']
            participant.record_attendance(session_id, is_present)

            db.session.commit()

            result = {
                'success': True,
                'message': f'Attendance record {action} successfully',
                'action': action,
                'participant': AttendanceService._format_participant_info(participant),
                'session': {
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'day': session.day,
                    'date': attendance_date.strftime('%Y-%m-%d')
                },
                'attendance': {
                    'status': status,
                    'is_correct_session': is_correct_session,
                    'check_in_method': 'manual_override'
                },
                'admin_user': {
                    'id': admin_user.id,
                    'username': admin_user.username,
                    'full_name': admin_user.full_name
                },
                'notes': notes
            }

            logger.info(
                f"Manual attendance override by {admin_user.username}: {participant.unique_id} marked {status} for session {session.time_slot}")
            return result

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during manual attendance override: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to process manual attendance override',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def get_real_time_attendance_stats(session_id=None, classroom=None, date=None):
        """
        Get real-time attendance statistics with optimized aggregation queries.

        Args:
            session_id: Specific session ID (optional)
            classroom: Specific classroom (optional)
            date: Specific date (defaults to today)

        Returns:
            dict: Real-time attendance statistics
        """
        logger = logging.getLogger('attendance_service')

        try:
            if date is None:
                date = datetime.now().date()
            elif isinstance(date, str):
                date = datetime.strptime(date, "%Y-%m-%d").date()

            # Base statistics query with optimized joins
            base_query = (
                db.session.query(
                    Session.id.label('session_id'),
                    Session.time_slot,
                    Session.day,
                    Participant.classroom,
                    func.count(Participant.id).label('expected_count'),
                    func.sum(
                        case(
                            (
                                and_(
                                    Attendance.id.isnot(None),
                                    Attendance.status == 'present'
                                ), 1
                            ),
                            else_=0
                        )
                    ).label('present_count'),
                    func.sum(
                        case(
                            (Attendance.is_correct_session == True, 1),
                            else_=0
                        )
                    ).label('correct_session_count')
                )
                .select_from(Session)
                .outerjoin(
                    Participant,
                    or_(
                        and_(Session.day == 'Saturday', Participant.saturday_session_id == Session.id),
                        and_(Session.day == 'Sunday', Participant.sunday_session_id == Session.id)
                    )
                )
                .outerjoin(
                    Attendance,
                    and_(
                        Attendance.participant_id == Participant.id,
                        Attendance.session_id == Session.id,
                        func.date(Attendance.timestamp) == date
                    )
                )
            )

            # Apply filters
            if session_id:
                base_query = base_query.filter(Session.id == session_id)

            if classroom:
                base_query = base_query.filter(Participant.classroom == classroom)

            # Group by session and classroom
            stats = (
                base_query
                .group_by(Session.id, Session.time_slot, Session.day, Participant.classroom)
                .order_by(Session.day, Session.time_slot, Participant.classroom)
                .all()
            )

            # Organize results
            result = {
                'success': True,
                'date': date.strftime('%Y-%m-%d'),
                'generated_at': datetime.now().isoformat(),
                'sessions': {}
            }

            global_stats = {
                'total_expected': 0,
                'total_present': 0,
                'total_correct_sessions': 0
            }

            for stat in stats:
                session_key = f"{stat.session_id}"

                if session_key not in result['sessions']:
                    result['sessions'][session_key] = {
                        'id': stat.session_id,
                        'time_slot': stat.time_slot,
                        'day': stat.day,
                        'classrooms': {},
                        'totals': {
                            'expected': 0,
                            'present': 0,
                            'correct_sessions': 0,
                            'attendance_rate': 0
                        }
                    }

                # Add classroom data
                classroom_key = stat.classroom or 'unknown'
                classroom_data = {
                    'expected': stat.expected_count or 0,
                    'present': stat.present_count or 0,
                    'correct_sessions': stat.correct_session_count or 0,
                    'attendance_rate': 0
                }

                if classroom_data['expected'] > 0:
                    classroom_data['attendance_rate'] = round(
                        (classroom_data['present'] / classroom_data['expected']) * 100, 1
                    )

                result['sessions'][session_key]['classrooms'][classroom_key] = classroom_data

                # Update session totals
                session_totals = result['sessions'][session_key]['totals']
                session_totals['expected'] += classroom_data['expected']
                session_totals['present'] += classroom_data['present']
                session_totals['correct_sessions'] += classroom_data['correct_sessions']

                # Update global stats
                global_stats['total_expected'] += classroom_data['expected']
                global_stats['total_present'] += classroom_data['present']
                global_stats['total_correct_sessions'] += classroom_data['correct_sessions']

            # Calculate session attendance rates
            for session_data in result['sessions'].values():
                totals = session_data['totals']
                if totals['expected'] > 0:
                    totals['attendance_rate'] = round(
                        (totals['present'] / totals['expected']) * 100, 1
                    )

            # Add global statistics
            if global_stats['total_expected'] > 0:
                global_stats['overall_attendance_rate'] = round(
                    (global_stats['total_present'] / global_stats['total_expected']) * 100, 1
                )
            else:
                global_stats['overall_attendance_rate'] = 0

            result['global_statistics'] = global_stats

            logger.info(f"Generated real-time attendance stats for {date}")
            return result

        except Exception as e:
            logger.error(f"Error generating real-time attendance stats: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to generate attendance statistics',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    @staticmethod
    def get_attendance_warnings(date=None, limit=50):
        """
        Get attendance warnings (wrong sessions, consecutive absences, etc.).

        Args:
            date: Date to check warnings for (defaults to today)
            limit: Maximum number of warnings to return

        Returns:
            dict: Attendance warnings and alerts
        """
        logger = logging.getLogger('attendance_service')

        try:
            if date is None:
                date = datetime.now().date()
            elif isinstance(date, str):
                date = datetime.strptime(date, "%Y-%m-%d").date()

            warnings = {
                'success': True,
                'date': date.strftime('%Y-%m-%d'),
                'wrong_session_attendees': [],
                'consecutive_absences': [],
                'inactive_participants': [],
                'generated_at': datetime.now().isoformat()
            }

            # Get wrong session attendees for today
            wrong_session_attendees = (
                db.session.query(Attendance)
                .options(
                    joinedload(Attendance.participant),
                    joinedload(Attendance.session)
                )
                .filter(
                    and_(
                        func.date(Attendance.timestamp) == date,
                        Attendance.is_correct_session == False,
                        Attendance.status == 'present'
                    )
                )
                .limit(limit)
                .all()
            )

            for record in wrong_session_attendees:
                participant = record.participant
                # Determine expected session
                is_saturday = record.session.day == 'Saturday'
                expected_session_id = (
                    participant.saturday_session_id if is_saturday
                    else participant.sunday_session_id
                )

                if expected_session_id:
                    expected_session = db.session.query(Session).get(expected_session_id)

                    warnings['wrong_session_attendees'].append({
                        'participant': AttendanceService._format_participant_info(participant),
                        'actual_session': {
                            'id': record.session.id,
                            'time_slot': record.session.time_slot,
                            'day': record.session.day
                        },
                        'expected_session': {
                            'id': expected_session.id,
                            'time_slot': expected_session.time_slot,
                            'day': expected_session.day
                        } if expected_session else None,
                        'timestamp': record.timestamp.strftime('%H:%M:%S')
                    })

            # Get participants with consecutive absences
            consecutive_absence_limit = current_app.config.get('CONSECUTIVE_ABSENCE_LIMIT', 3)
            consecutive_absences = (
                db.session.query(Participant)
                .options(joinedload(Participant.user))
                .filter(
                    Participant.consecutive_missed_sessions >= consecutive_absence_limit
                )
                .limit(limit)
                .all()
            )

            for participant in consecutive_absences:
                warnings['consecutive_absences'].append({
                    'participant': AttendanceService._format_participant_info(participant),
                    'consecutive_missed_sessions': participant.consecutive_missed_sessions,
                    'is_active': participant.user.is_active if participant.user else True
                })

            # Get recently deactivated participants due to absences
            inactive_participants = (
                db.session.query(Participant)
                .join(Participant.user)
                .filter(
                    and_(
                        User.is_active == False,
                        Participant.consecutive_missed_sessions >= consecutive_absence_limit
                    )
                )
                .limit(limit)
                .all()
            )

            for participant in inactive_participants:
                warnings['inactive_participants'].append({
                    'participant': AttendanceService._format_participant_info(participant),
                    'consecutive_missed_sessions': participant.consecutive_missed_sessions,
                    'deactivated_at': participant.user.updated_at.strftime(
                        '%Y-%m-%d %H:%M:%S') if participant.user else None
                })

            # Add summary counts
            warnings['summary'] = {
                'wrong_session_count': len(warnings['wrong_session_attendees']),
                'consecutive_absence_count': len(warnings['consecutive_absences']),
                'inactive_participant_count': len(warnings['inactive_participants']),
                'total_warnings': len(warnings['wrong_session_attendees']) + len(
                    warnings['consecutive_absences']) + len(warnings['inactive_participants'])
            }

            logger.info(
                f"Generated attendance warnings for {date}: {warnings['summary']['total_warnings']} total warnings")
            return warnings

        except Exception as e:
            logger.error(f"Error generating attendance warnings: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Failed to generate attendance warnings',
                'error_code': AttendanceError.DATABASE_ERROR
            }

    # Helper Methods

    @staticmethod
    def _resolve_session(session_identifier):
        """
        Resolve session from identifier (time slot string or session ID).

        Returns:
            tuple: (session, day_name) or (None, None) if not found
        """
        current_time = datetime.now()
        day_name = current_time.strftime('%A')

        # Default to weekend for testing if not Saturday/Sunday
        if day_name not in ['Saturday', 'Sunday']:
            day_name = 'Saturday'  # Default for testing

        try:
            # Try to find by session ID first
            if isinstance(session_identifier, int) or session_identifier.isdigit():
                session = db.session.query(Session).filter_by(id=int(session_identifier)).first()
                if session:
                    return session, session.day

            # Try to find by time slot and current day
            session = (
                db.session.query(Session)
                .filter_by(day=day_name, time_slot=session_identifier)
                .first()
            )

            if session:
                return session, day_name

            # Try the other day if not found
            other_day = 'Sunday' if day_name == 'Saturday' else 'Saturday'
            session = (
                db.session.query(Session)
                .filter_by(day=other_day, time_slot=session_identifier)
                .first()
            )

            if session:
                return session, other_day

            return None, None

        except Exception:
            return None, None

    @staticmethod
    def _format_participant_info(participant):
        """Format participant information for responses."""
        return {
            'id': participant.id,
            'unique_id': participant.unique_id,
            'full_name': participant.full_name,
            'email': participant.email,
            'phone': participant.phone,
            'has_laptop': participant.has_laptop,
            'classroom': participant.classroom,
            'consecutive_missed_sessions': participant.consecutive_missed_sessions,
            'is_active': participant.user.is_active if participant.user else True
        }

    @staticmethod
    def _send_wrong_session_notification(participant, current_session, expected_session):
        """Send notification for wrong session attendance."""
        try:
            if not email_service:
                return

            template_context = {
                'participant': participant,
                'current_session': current_session,
                'expected_session': expected_session,
                'notification_time': datetime.now()
            }

            email_service.send_notification(
                recipient=participant.email,
                template='wrong_session_alert',
                subject=f'Session Attendance Alert - {current_app.config.get("SITE_NAME", "Programming Course")}',
                template_context=template_context,
                priority=Priority.HIGH,
                group_id='wrong_session_alerts'
            )

        except Exception as e:
            logging.getLogger('attendance_service').warning(f"Failed to send wrong session notification: {e}")
