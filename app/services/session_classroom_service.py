# services/session_classroom_service.py
"""
Unified Session and Classroom Management Service.
Handles all session initialization, classroom assignment, capacity management,
reassignment workflows, and session analytics with optimized database operations.
"""

import re
import logging
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy import and_, or_, func, case, exists, text
from sqlalchemy.orm import joinedload, selectinload, contains_eager
from sqlalchemy.exc import IntegrityError

from app.models.session import Session
from app.models.participant import Participant
from app.models.session_reassignment import SessionReassignmentRequest, ReassignmentStatus
from app.models.attendance import Attendance
from app.extensions import db


class SessionClassroomService:
    """Optimized service for comprehensive session and classroom management."""

    # ===============================
    # SESSION INITIALIZATION & MANAGEMENT
    # ===============================

    @staticmethod
    def init_sessions_from_config():
        """
        Initialize session data from application configuration.
        Optimized to avoid duplicates and batch create sessions.

        Returns:
            dict: Results of session initialization
        """
        logger = logging.getLogger('session_classroom_service')

        try:
            # Check if sessions already exist (optimized count query)
            existing_count = db.session.query(func.count(Session.id)).scalar()

            if existing_count > 0:
                logger.info(f"Sessions already initialized ({existing_count} sessions exist)")
                return {
                    'success': True,
                    'message': f'Sessions already initialized ({existing_count} existing)',
                    'created_count': 0,
                    'existing_count': existing_count
                }

            # Get session configurations
            saturday_sessions = current_app.config.get('SATURDAY_SESSIONS', [])
            sunday_sessions = current_app.config.get('SUNDAY_SESSIONS', [])

            # Batch create sessions
            sessions_to_create = []

            # Add Saturday sessions
            for time_slot in saturday_sessions:
                normalized_time = SessionClassroomService.normalize_session_time(time_slot)
                sessions_to_create.append(Session(
                    time_slot=normalized_time,
                    day='Saturday',
                    max_capacity=current_app.config.get('DEFAULT_SESSION_CAPACITY', 30),
                    is_active=True
                ))

            # Add Sunday sessions
            for time_slot in sunday_sessions:
                normalized_time = SessionClassroomService.normalize_session_time(time_slot)
                sessions_to_create.append(Session(
                    time_slot=normalized_time,
                    day='Sunday',
                    max_capacity=current_app.config.get('DEFAULT_SESSION_CAPACITY', 30),
                    is_active=True
                ))

            # Bulk insert sessions
            db.session.add_all(sessions_to_create)
            db.session.commit()

            created_count = len(sessions_to_create)
            logger.info(f"Successfully initialized {created_count} sessions")

            return {
                'success': True,
                'message': f'Successfully created {created_count} sessions',
                'created_count': created_count,
                'existing_count': 0
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to initialize sessions: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def normalize_session_time(session_time):
        """
        Normalize session time format for consistent storage.

        Args:
            session_time: Time string in various formats

        Returns:
            str: Normalized time string
        """
        if not session_time:
            return ""

        # Clean the string
        session_time = str(session_time).strip()

        # Fix spacing around hyphens: '12.00pm- 1.30pm' -> '12.00pm - 1.30pm'
        session_time = re.sub(r'\s*-\s*', ' - ', session_time)

        return session_time

    @staticmethod
    def get_sessions_by_day(day, include_inactive=False):
        """
        Get all sessions for a specific day with optimized query.

        Args:
            day: 'Saturday' or 'Sunday'
            include_inactive: Include inactive sessions

        Returns:
            list: List of Session objects
        """
        try:
            query = db.session.query(Session).filter_by(day=day)

            if not include_inactive:
                query = query.filter_by(is_active=True)

            # Order by time slot for consistent results
            return query.order_by(Session.time_slot).all()

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting sessions for {day}: {str(e)}")
            raise

    @staticmethod
    def get_session_by_time_and_day(time_slot, day):
        """
        Get specific session by time slot and day.

        Args:
            time_slot: Session time slot
            day: 'Saturday' or 'Sunday'

        Returns:
            Session: Session object or None
        """
        try:
            normalized_time = SessionClassroomService.normalize_session_time(time_slot)

            return (
                db.session.query(Session)
                .filter_by(day=day, time_slot=normalized_time, is_active=True)
                .first()
            )

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting session: {str(e)}")
            return None

    # ===============================
    # CLASSROOM MANAGEMENT
    # ===============================

    @staticmethod
    def determine_classroom_assignment(has_laptop, admin_override_classroom=None):
        """
        Determine classroom assignment based on laptop status and configuration.

        Args:
            has_laptop: Boolean indicating laptop ownership
            admin_override_classroom: Admin-selected classroom (may be overridden)

        Returns:
            str: Assigned classroom number
        """
        try:
            # Check if auto-assignment is enabled
            auto_assign = current_app.config.get('AUTO_ASSIGN_BY_LAPTOP', True)

            if auto_assign:
                # Auto-assign based on laptop status (override admin selection)
                return (
                    current_app.config['LAPTOP_CLASSROOM'] if has_laptop
                    else current_app.config['NO_LAPTOP_CLASSROOM']
                )
            else:
                # Use admin-selected classroom or fall back to laptop-based assignment
                return admin_override_classroom or (
                    current_app.config['LAPTOP_CLASSROOM'] if has_laptop
                    else current_app.config['NO_LAPTOP_CLASSROOM']
                )

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error determining classroom: {str(e)}")
            # Fall back to laptop-based assignment
            return (
                current_app.config.get('LAPTOP_CLASSROOM', '205') if has_laptop
                else current_app.config.get('NO_LAPTOP_CLASSROOM', '203')
            )

    @staticmethod
    def get_classroom_capacity(classroom):
        """
        Get capacity for a specific classroom.

        Args:
            classroom: Classroom identifier

        Returns:
            int: Classroom capacity
        """
        capacities = current_app.config.get('SESSION_CAPACITY', {})
        return capacities.get(classroom, 30)  # Default to 30 if not specified

    @staticmethod
    def get_classroom_utilization(classroom=None):
        """
        Get classroom utilization statistics with optimized queries.

        Args:
            classroom: Specific classroom or None for all classrooms

        Returns:
            dict: Utilization statistics
        """
        try:
            if classroom:
                # Single classroom utilization
                capacity = SessionClassroomService.get_classroom_capacity(classroom)
                current_count = (
                    db.session.query(func.count(Participant.id))
                    .filter_by(classroom=classroom)
                    .scalar()
                )

                return {
                    'classroom': classroom,
                    'capacity': capacity,
                    'current_count': current_count,
                    'available_spots': capacity - current_count,
                    'utilization_percentage': round((current_count / capacity) * 100, 1) if capacity > 0 else 0
                }

            else:
                # All classrooms utilization (optimized with single query)
                classroom_stats = (
                    db.session.query(
                        Participant.classroom,
                        func.count(Participant.id).label('count')
                    )
                    .group_by(Participant.classroom)
                    .all()
                )

                # Get all configured classrooms
                all_classrooms = [
                    current_app.config.get('LAPTOP_CLASSROOM', '205'),
                    current_app.config.get('NO_LAPTOP_CLASSROOM', '203')
                ]

                results = {}
                for classroom_num in all_classrooms:
                    capacity = SessionClassroomService.get_classroom_capacity(classroom_num)
                    current_count = next((stat.count for stat in classroom_stats if stat.classroom == classroom_num), 0)

                    results[classroom_num] = {
                        'capacity': capacity,
                        'current_count': current_count,
                        'available_spots': capacity - current_count,
                        'utilization_percentage': round((current_count / capacity) * 100, 1) if capacity > 0 else 0
                    }

                return results

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting classroom utilization: {str(e)}")
            raise

    # ===============================
    # SESSION CAPACITY & ASSIGNMENT
    # ===============================

    @staticmethod
    def get_session_participant_count(session_id, classroom, day=None):
        """
        Get current participant count for a session in a specific classroom.
        Optimized with single query covering both Saturday and Sunday.

        Args:
            session_id: Session ID
            classroom: Classroom identifier
            day: Specific day or None for both days

        Returns:
            int: Current participant count
        """
        try:
            if day:
                # Count for specific day only
                if day == 'Saturday':
                    return (
                        db.session.query(func.count(Participant.id))
                        .filter_by(classroom=classroom, saturday_session_id=session_id)
                        .scalar()
                    )
                else:  # Sunday
                    return (
                        db.session.query(func.count(Participant.id))
                        .filter_by(classroom=classroom, sunday_session_id=session_id)
                        .scalar()
                    )
            else:
                # Count for both days (maximum of Saturday or Sunday)
                saturday_count = (
                    db.session.query(func.count(Participant.id))
                    .filter_by(classroom=classroom, saturday_session_id=session_id)
                    .scalar()
                )

                sunday_count = (
                    db.session.query(func.count(Participant.id))
                    .filter_by(classroom=classroom, sunday_session_id=session_id)
                    .scalar()
                )

                return max(saturday_count, sunday_count)

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting session count: {str(e)}")
            return 0

    @staticmethod
    def get_available_sessions_with_capacity(day, has_laptop, current_session_id=None):
        """
        Get all sessions for a day with detailed capacity information.
        Optimized for reassignment workflow.

        Args:
            day: 'Saturday' or 'Sunday'
            has_laptop: Boolean for classroom determination
            current_session_id: Current session to exclude from results

        Returns:
            list: Sessions with capacity details
        """
        try:
            # Determine target classroom
            classroom = SessionClassroomService.determine_classroom_assignment(has_laptop)
            classroom_capacity = SessionClassroomService.get_classroom_capacity(classroom)

            # Get all sessions for the day with participant counts
            sessions_query = (
                db.session.query(Session)
                .filter_by(day=day, is_active=True)
                .order_by(Session.time_slot)
            )

            sessions = sessions_query.all()

            results = []
            for session in sessions:
                # Skip current session if specified
                if current_session_id and session.id == current_session_id:
                    continue

                # Get current count for this session/classroom combination
                current_count = SessionClassroomService.get_session_participant_count(
                    session.id, classroom, day
                )

                available_spots = classroom_capacity - current_count

                results.append({
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'capacity': {
                        'total': classroom_capacity,
                        'used': current_count,
                        'available': available_spots,
                        'percentage_filled': round((current_count / classroom_capacity) * 100,
                                                   1) if classroom_capacity > 0 else 0
                    },
                    'has_capacity': available_spots > 0,
                    'is_recommended': available_spots > 0  # Can be enhanced with additional logic
                })

            return results

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting available sessions: {str(e)}")
            raise

    @staticmethod
    def find_best_available_session(day, has_laptop, exclude_session_id=None):
        """
        Find the session with the most available capacity for assignment.

        Args:
            day: 'Saturday' or 'Sunday'
            has_laptop: Boolean for classroom determination
            exclude_session_id: Session to exclude from search

        Returns:
            Session: Best available session or None
        """
        try:
            available_sessions = SessionClassroomService.get_available_sessions_with_capacity(
                day, has_laptop, exclude_session_id
            )

            # Filter to only sessions with available capacity
            available_sessions = [s for s in available_sessions if s['has_capacity']]

            if not available_sessions:
                return None

            # Sort by most available spots (descending)
            best_session_info = max(available_sessions, key=lambda x: x['capacity']['available'])

            return SessionClassroomService.get_session_by_time_and_day(
                best_session_info['time_slot'], day
            )

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error finding best session: {str(e)}")
            return None

    @staticmethod
    def assign_participant_sessions(has_laptop, preferred_saturday_id=None, preferred_sunday_id=None):
        """
        Assign Saturday and Sunday sessions to a participant with capacity checking.

        Args:
            has_laptop: Boolean for classroom determination
            preferred_saturday_id: Preferred Saturday session ID
            preferred_sunday_id: Preferred Sunday session ID

        Returns:
            dict: Assignment results with session IDs and any reassignments
        """
        try:
            results = {
                'saturday_session_id': None,
                'sunday_session_id': None,
                'reassignments': [],
                'warnings': []
            }

            # Assign Saturday session
            if preferred_saturday_id:
                preferred_saturday = db.session.query(Session).get(preferred_saturday_id)
                if preferred_saturday and preferred_saturday.day == 'Saturday':
                    # Check if preferred session has capacity
                    classroom = SessionClassroomService.determine_classroom_assignment(has_laptop)
                    current_count = SessionClassroomService.get_session_participant_count(
                        preferred_saturday_id, classroom, 'Saturday'
                    )
                    capacity = SessionClassroomService.get_classroom_capacity(classroom)

                    if current_count < capacity:
                        results['saturday_session_id'] = preferred_saturday_id
                    else:
                        # Find alternative
                        alternative = SessionClassroomService.find_best_available_session(
                            'Saturday', has_laptop, preferred_saturday_id
                        )
                        if alternative:
                            results['saturday_session_id'] = alternative.id
                            results['reassignments'].append({
                                'day': 'Saturday',
                                'original': preferred_saturday.time_slot,
                                'assigned': alternative.time_slot,
                                'reason': 'Preferred session at capacity'
                            })
                        else:
                            results['warnings'].append('No available Saturday sessions')

            # If no Saturday session assigned yet, find best available
            if not results['saturday_session_id']:
                saturday_session = SessionClassroomService.find_best_available_session('Saturday', has_laptop)
                if saturday_session:
                    results['saturday_session_id'] = saturday_session.id
                else:
                    results['warnings'].append('No available Saturday sessions')

            # Assign Sunday session (similar logic)
            if preferred_sunday_id:
                preferred_sunday = db.session.query(Session).get(preferred_sunday_id)
                if preferred_sunday and preferred_sunday.day == 'Sunday':
                    classroom = SessionClassroomService.determine_classroom_assignment(has_laptop)
                    current_count = SessionClassroomService.get_session_participant_count(
                        preferred_sunday_id, classroom, 'Sunday'
                    )
                    capacity = SessionClassroomService.get_classroom_capacity(classroom)

                    if current_count < capacity:
                        results['sunday_session_id'] = preferred_sunday_id
                    else:
                        alternative = SessionClassroomService.find_best_available_session(
                            'Sunday', has_laptop, preferred_sunday_id
                        )
                        if alternative:
                            results['sunday_session_id'] = alternative.id
                            results['reassignments'].append({
                                'day': 'Sunday',
                                'original': preferred_sunday.time_slot,
                                'assigned': alternative.time_slot,
                                'reason': 'Preferred session at capacity'
                            })
                        else:
                            results['warnings'].append('No available Sunday sessions')

            # If no Sunday session assigned yet, find best available
            if not results['sunday_session_id']:
                sunday_session = SessionClassroomService.find_best_available_session('Sunday', has_laptop)
                if sunday_session:
                    results['sunday_session_id'] = sunday_session.id
                else:
                    results['warnings'].append('No available Sunday sessions')

            return results

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error assigning sessions: {str(e)}")
            raise

    # ===============================
    # REASSIGNMENT REQUEST MANAGEMENT
    # ===============================

    @staticmethod
    def create_reassignment_request(participant_id, day_type, requested_session_id, reason):
        """
        Create a new session reassignment request with comprehensive validation.

        Args:
            participant_id: Participant ID
            day_type: 'Saturday' or 'Sunday'
            requested_session_id: Target session ID
            reason: Reason for reassignment

        Returns:
            dict: Creation result
        """
        logger = logging.getLogger('session_classroom_service')

        try:
            # Get participant with optimized query (eager load sessions)
            participant = (
                db.session.query(Participant)
                .options(
                    joinedload(Participant.saturday_session),
                    joinedload(Participant.sunday_session)
                )
                .filter_by(id=participant_id)
                .first()
            )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': 'participant_not_found'
                }

            # Check reassignment limit
            max_reassignments = current_app.config.get('MAX_REASSIGNMENTS_PER_PARTICIPANT', 2)
            if participant.reassignments_count >= max_reassignments:
                return {
                    'success': False,
                    'message': f'Maximum number of reassignments ({max_reassignments}) reached',
                    'error_code': 'max_reassignments_reached'
                }

            # Validate day type
            if day_type not in ['Saturday', 'Sunday']:
                return {
                    'success': False,
                    'message': 'Invalid day type. Must be Saturday or Sunday',
                    'error_code': 'invalid_day_type'
                }

            # Get current session ID
            current_session_id = (
                participant.saturday_session_id if day_type == 'Saturday'
                else participant.sunday_session_id
            )

            # Validate requested session
            requested_session = db.session.query(Session).get(requested_session_id)
            if not requested_session:
                return {
                    'success': False,
                    'message': 'Requested session not found',
                    'error_code': 'session_not_found'
                }

            # Validate session day matches request
            if requested_session.day != day_type:
                return {
                    'success': False,
                    'message': f'Requested session is not a {day_type} session',
                    'error_code': 'session_day_mismatch'
                }

            # Check if requesting same session
            if current_session_id == requested_session_id:
                return {
                    'success': False,
                    'message': 'Cannot request reassignment to the same session',
                    'error_code': 'same_session_requested'
                }

            # Check session capacity
            classroom = participant.classroom
            current_count = SessionClassroomService.get_session_participant_count(
                requested_session_id, classroom, day_type
            )
            capacity = SessionClassroomService.get_classroom_capacity(classroom)

            if current_count >= capacity:
                return {
                    'success': False,
                    'message': 'Requested session has no available capacity',
                    'error_code': 'session_at_capacity'
                }

            # Check for existing pending request (optimized query)
            existing_request_exists = db.session.query(
                exists().where(
                    and_(
                        SessionReassignmentRequest.participant_id == participant_id,
                        SessionReassignmentRequest.day_type == day_type,
                        SessionReassignmentRequest.status == ReassignmentStatus.PENDING
                    )
                )
            ).scalar()

            if existing_request_exists:
                return {
                    'success': False,
                    'message': 'You already have a pending request for this day',
                    'error_code': 'pending_request_exists'
                }

            # Create new request
            new_request = SessionReassignmentRequest(
                participant_id=participant_id,
                current_session_id=current_session_id,
                requested_session_id=requested_session_id,
                day_type=day_type,
                reason=reason.strip() if reason else '',
                priority='normal'  # Can be enhanced based on business rules
            )

            db.session.add(new_request)
            db.session.commit()

            logger.info(
                f"Reassignment request created: Participant {participant.unique_id}, "
                f"{day_type} session change requested"
            )

            return {
                'success': True,
                'message': 'Reassignment request submitted successfully',
                'request_id': new_request.id,
                'current_session': participant.saturday_session.time_slot if day_type == 'Saturday' else participant.sunday_session.time_slot,
                'requested_session': requested_session.time_slot
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating reassignment request: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'An error occurred while creating the request',
                'error_code': 'system_error'
            }

    @staticmethod
    def get_pending_reassignment_requests(limit=50, offset=0):
        """
        Get pending reassignment requests for admin review with optimized queries.

        Args:
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            list: Pending requests with participant and session details
        """
        try:
            # Optimized query with eager loading
            requests = (
                db.session.query(SessionReassignmentRequest)
                .options(
                    contains_eager(SessionReassignmentRequest.participant),
                    joinedload(SessionReassignmentRequest.current_session),
                    joinedload(SessionReassignmentRequest.requested_session)
                )
                .join(SessionReassignmentRequest.participant)
                .filter(SessionReassignmentRequest.status == ReassignmentStatus.PENDING)
                .order_by(
                    SessionReassignmentRequest.priority.desc(),  # High priority first
                    SessionReassignmentRequest.created_at.asc()  # Oldest first
                )
                .limit(limit)
                .offset(offset)
                .all()
            )

            results = []
            for req in requests:
                participant = req.participant

                results.append({
                    'id': req.id,
                    'participant': {
                        'id': participant.id,
                        'unique_id': participant.unique_id,
                        'full_name': participant.full_name,
                        'email': participant.email,
                        'has_laptop': participant.has_laptop,
                        'classroom': participant.classroom,
                        'reassignments_count': participant.reassignments_count
                    },
                    'day_type': req.day_type,
                    'current_session': req.current_session.time_slot,
                    'requested_session': req.requested_session.time_slot,
                    'reason': req.reason,
                    'priority': req.priority,
                    'created_at': req.created_at.isoformat(),
                    'days_pending': (datetime.now() - req.created_at).days
                })

            return results

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting pending requests: {str(e)}")
            raise

    @staticmethod
    def process_reassignment_request(request_id, admin_id, approve, admin_notes=None):
        """
        Process (approve or reject) a reassignment request with optimized updates.

        Args:
            request_id: Request ID to process
            admin_id: Admin user ID
            approve: Boolean - approve (True) or reject (False)
            admin_notes: Optional admin notes

        Returns:
            dict: Processing result
        """
        logger = logging.getLogger('session_classroom_service')

        try:
            # Get request with participant data (optimized query)
            request = (
                db.session.query(SessionReassignmentRequest)
                .options(
                    joinedload(SessionReassignmentRequest.participant),
                    joinedload(SessionReassignmentRequest.requested_session)
                )
                .filter_by(id=request_id)
                .first()
            )

            if not request:
                return {
                    'success': False,
                    'message': 'Reassignment request not found',
                    'error_code': 'request_not_found'
                }

            # Check if already processed
            if request.status != ReassignmentStatus.PENDING:
                return {
                    'success': False,
                    'message': f'Request has already been {request.status}',
                    'error_code': 'request_already_processed'
                }

            # Update request status
            request.status = ReassignmentStatus.APPROVED if approve else ReassignmentStatus.REJECTED
            request.admin_notes = admin_notes.strip() if admin_notes else None
            request.reviewed_at = datetime.now()
            # Note: Need to add reviewed_by field to model if not exists

            if approve:
                participant = request.participant

                # Double-check capacity before approval
                classroom = participant.classroom
                current_count = SessionClassroomService.get_session_participant_count(
                    request.requested_session_id, classroom, request.day_type
                )
                capacity = SessionClassroomService.get_classroom_capacity(classroom)

                if current_count >= capacity:
                    return {
                        'success': False,
                        'message': 'Requested session no longer has available capacity',
                        'error_code': 'session_now_at_capacity'
                    }

                # Update participant session assignment
                if request.day_type == 'Saturday':
                    participant.saturday_session_id = request.requested_session_id
                else:
                    participant.sunday_session_id = request.requested_session_id

                # Increment reassignment count
                participant.reassignments_count += 1

                logger.info(
                    f"Reassignment approved: Participant {participant.unique_id} "
                    f"moved to {request.day_type} session {request.requested_session.time_slot}"
                )

            # Commit all changes
            db.session.commit()

            return {
                'success': True,
                'message': f'Request has been {"approved" if approve else "rejected"}',
                'request_id': request.id,
                'status': request.status,
                'participant_id': request.participant.unique_id
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error processing reassignment request: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'An error occurred while processing the request',
                'error_code': 'system_error'
            }

    @staticmethod
    def get_participant_reassignment_history(participant_id, limit=10):
        """
        Get reassignment history for a specific participant.

        Args:
            participant_id: Participant ID
            limit: Maximum number of results

        Returns:
            list: Reassignment request history
        """
        try:
            requests = (
                db.session.query(SessionReassignmentRequest)
                .options(
                    joinedload(SessionReassignmentRequest.current_session),
                    joinedload(SessionReassignmentRequest.requested_session)
                )
                .filter_by(participant_id=participant_id)
                .order_by(SessionReassignmentRequest.created_at.desc())
                .limit(limit)
                .all()
            )

            results = []
            for req in requests:
                results.append({
                    'id': req.id,
                    'day_type': req.day_type,
                    'current_session': req.current_session.time_slot,
                    'requested_session': req.requested_session.time_slot,
                    'reason': req.reason,
                    'status': req.status,
                    'admin_notes': req.admin_notes,
                    'created_at': req.created_at.isoformat(),
                    'reviewed_at': req.reviewed_at.isoformat() if req.reviewed_at else None
                })

            return results

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting reassignment history: {str(e)}")
            raise

    # ===============================
    # ANALYTICS & REPORTING
    # ===============================

    @staticmethod
    def get_comprehensive_session_report():
        """
        Get comprehensive session utilization report with optimized aggregation queries.

        Returns:
            dict: Detailed session analytics
        """
        try:
            # Get session utilization by day and time (optimized aggregation)
            session_stats = {}

            for day in ['Saturday', 'Sunday']:
                sessions = SessionClassroomService.get_sessions_by_day(day)
                day_stats = []

                for session in sessions:
                    # Get participant counts for both classrooms
                    laptop_classroom = current_app.config.get('LAPTOP_CLASSROOM', '205')
                    no_laptop_classroom = current_app.config.get('NO_LAPTOP_CLASSROOM', '203')

                    laptop_count = SessionClassroomService.get_session_participant_count(
                        session.id, laptop_classroom, day
                    )
                    no_laptop_count = SessionClassroomService.get_session_participant_count(
                        session.id, no_laptop_classroom, day
                    )

                    laptop_capacity = SessionClassroomService.get_classroom_capacity(laptop_classroom)
                    no_laptop_capacity = SessionClassroomService.get_classroom_capacity(no_laptop_classroom)

                    total_count = laptop_count + no_laptop_count
                    total_capacity = laptop_capacity + no_laptop_capacity

                    day_stats.append({
                        'session_id': session.id,
                        'time_slot': session.time_slot,
                        'laptop_classroom': {
                            'participants': laptop_count,
                            'capacity': laptop_capacity,
                            'utilization': round((laptop_count / laptop_capacity) * 100,
                                                 1) if laptop_capacity > 0 else 0
                        },
                        'no_laptop_classroom': {
                            'participants': no_laptop_count,
                            'capacity': no_laptop_capacity,
                            'utilization': round((no_laptop_count / no_laptop_capacity) * 100,
                                                 1) if no_laptop_capacity > 0 else 0
                        },
                        'total': {
                            'participants': total_count,
                            'capacity': total_capacity,
                            'utilization': round((total_count / total_capacity) * 100, 1) if total_capacity > 0 else 0
                        }
                    })

                session_stats[day.lower()] = day_stats

            # Get overall statistics
            total_participants = db.session.query(func.count(Participant.id)).scalar()

            # Classroom distribution
            classroom_distribution = (
                db.session.query(
                    Participant.classroom,
                    func.count(Participant.id).label('count')
                )
                .group_by(Participant.classroom)
                .all()
            )

            # Reassignment statistics
            reassignment_stats = (
                db.session.query(
                    SessionReassignmentRequest.status,
                    func.count(SessionReassignmentRequest.id).label('count')
                )
                .group_by(SessionReassignmentRequest.status)
                .all()
            )

            return {
                'session_utilization': session_stats,
                'overview': {
                    'total_participants': total_participants,
                    'classroom_distribution': {row.classroom: row.count for row in classroom_distribution},
                    'reassignment_requests': {row.status: row.count for row in reassignment_stats}
                },
                'generated_at': datetime.now().isoformat()
            }

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error generating session report: {str(e)}")
            raise

    @staticmethod
    def get_capacity_warnings():
        """
        Get sessions that are at or near capacity.

        Returns:
            dict: Capacity warning information
        """
        try:
            warnings = {
                'at_capacity': [],
                'near_capacity': [],  # >90% full
                'over_capacity': []  # Should not happen but check anyway
            }

            for day in ['Saturday', 'Sunday']:
                sessions = SessionClassroomService.get_sessions_by_day(day)

                for session in sessions:
                    for classroom in [current_app.config.get('LAPTOP_CLASSROOM', '205'),
                                      current_app.config.get('NO_LAPTOP_CLASSROOM', '203')]:

                        current_count = SessionClassroomService.get_session_participant_count(
                            session.id, classroom, day
                        )
                        capacity = SessionClassroomService.get_classroom_capacity(classroom)
                        utilization = (current_count / capacity) * 100 if capacity > 0 else 0

                        session_info = {
                            'session_id': session.id,
                            'day': day,
                            'time_slot': session.time_slot,
                            'classroom': classroom,
                            'current_count': current_count,
                            'capacity': capacity,
                            'utilization_percentage': round(utilization, 1)
                        }

                        if current_count > capacity:
                            warnings['over_capacity'].append(session_info)
                        elif current_count == capacity:
                            warnings['at_capacity'].append(session_info)
                        elif utilization >= 90:
                            warnings['near_capacity'].append(session_info)

            return warnings

        except Exception as e:
            logging.getLogger('session_classroom_service').error(f"Error getting capacity warnings: {str(e)}")
            raise
        