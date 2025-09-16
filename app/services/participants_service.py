# services/participants_service.py
"""
Optimized Participants Service for participant-specific portal operations.
Provides read-only profile management, attendance analytics, and session management
with proper RBAC and optimized database queries.
"""
import calendar
import os
import secrets
import logging
from datetime import datetime, timedelta
from flask import current_app, url_for
from sqlalchemy import and_, or_, func, exists, case, desc
from sqlalchemy.orm import joinedload, selectinload, contains_eager
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from app.models.participant import Participant
from app.models.user import User, RoleType, Permission
from app.models.attendance import Attendance
from app.models.session import Session
from app.models.session_reassignment import SessionReassignmentRequest, ReassignmentStatus
from app.services.attendance_service import AttendanceService
from app.services.session_classroom_service import SessionClassroomService
from app.services.qr_code_service import QRCodeService
from app.extensions import db
from app.config import Config
from app.utils.auth import PermissionChecker


class ParticipantsError:
    """Participants service error codes."""
    PARTICIPANT_NOT_FOUND = 'participant_not_found'
    PERMISSION_DENIED = 'permission_denied'
    INVALID_FILE_TYPE = 'invalid_file_type'
    FILE_UPLOAD_FAILED = 'file_upload_failed'
    INVALID_SESSION = 'invalid_session'
    REQUEST_FAILED = 'request_failed'


class ParticipantsService:
    """Optimized service for participant portal operations."""

    # ===============================
    # PROFILE & DATA ACCESS
    # ===============================

    @staticmethod
    def get_participant_profile(participant_id, requesting_user_id):
        """
        Get participant profile with optimized loading and permission validation.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting the data

        Returns:
            dict: Profile data with permission-filtered content
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get requesting user with roles (optimized)
            requesting_user = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant)
                )
                .filter_by(id=requesting_user_id)
                .first()
            )

            if not requesting_user:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Invalid user'
                }

            # Get participant with session data (optimized)
            participant = (
                db.session.query(Participant)
                .options(
                    joinedload(Participant.saturday_session),
                    joinedload(Participant.sunday_session),
                    joinedload(Participant.user)
                )
                .filter_by(id=participant_id)
                .first()
            )

            if not participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PARTICIPANT_NOT_FOUND,
                    'message': 'Participant not found'
                }

            # Permission validation using existing logic
            if not PermissionChecker.can_view_participant(requesting_user, participant):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Access denied'
                }

            # Build profile data
            profile_data = {
                'success': True,
                'participant': {
                    'id': participant.id,
                    'unique_id': participant.unique_id,
                    'full_name': participant.full_name,
                    'first_name': participant.first_name,
                    'surname': participant.surname,
                    'email': participant.email,
                    'phone': participant.phone,
                    'has_laptop': participant.has_laptop,
                    'classroom': participant.classroom,
                    'profile_photo_url': ParticipantsService._get_profile_photo_url(
                        participant.profile_photo_path) if hasattr(participant,
                                                                   'profile_photo_path') and participant.profile_photo_path else None,
                    'registration_timestamp': participant.registration_timestamp.isoformat(),
                    'consecutive_missed_sessions': participant.consecutive_missed_sessions,
                    'reassignments_count': participant.reassignments_count
                },
                'sessions': {
                    'saturday': {
                        'id': participant.saturday_session.id if participant.saturday_session else None,
                        'time_slot': participant.saturday_session.time_slot if participant.saturday_session else None,
                        'day': 'Saturday'
                    },
                    'sunday': {
                        'id': participant.sunday_session.id if participant.sunday_session else None,
                        'time_slot': participant.sunday_session.time_slot if participant.sunday_session else None,
                        'day': 'Sunday'
                    }
                },
                'account_status': {
                    'is_active': participant.user.is_active if participant.user else False,
                    'has_account': participant.user is not None
                }
            }

            # Add classroom info
            classroom_name = 'Computer Lab (Laptop Required)' if participant.classroom == current_app.config.get(
                'LAPTOP_CLASSROOM', '205') else 'Regular Classroom'
            profile_data['participant']['classroom_name'] = classroom_name

            logger.info(f"Retrieved profile for participant {participant.unique_id}")
            return profile_data

        except Exception as e:
            logger.error(f"Error retrieving participant profile: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving profile'
            }

    @staticmethod
    def get_participant_dashboard_data(participant_id, requesting_user_id):
        """
        Get comprehensive dashboard data with optimized queries.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting the data

        Returns:
            dict: Dashboard data including profile, attendance, and warnings
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check first
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            # Get attendance summary using existing service
            attendance_result = AttendanceService.get_participant_attendance_summary(
                participant_id,
                include_sessions=False
            )

            # Get recent attendance (last 10 records)
            recent_attendance = (
                db.session.query(Attendance)
                .options(joinedload(Attendance.session))
                .filter_by(participant_id=participant_id)
                .order_by(desc(Attendance.timestamp))
                .limit(10)
                .all()
            )

            # Format recent attendance
            recent_records = []
            for record in recent_attendance:
                recent_records.append({
                    'date': record.timestamp.strftime('%Y-%m-%d'),
                    'time': record.timestamp.strftime('%H:%M'),
                    'session': record.session.time_slot,
                    'day': record.session.day,
                    'status': record.status,
                    'is_correct_session': record.is_correct_session
                })

            # Get attendance warnings for this participant
            participant = db.session.query(Participant).filter_by(id=participant_id).first()
            warnings = []

            if participant.consecutive_missed_sessions >= 2:
                warnings.append({
                    'type': 'consecutive_absences',
                    'message': f'You have missed {participant.consecutive_missed_sessions} consecutive sessions',
                    'severity': 'warning' if participant.consecutive_missed_sessions < 3 else 'danger'
                })

            # Check for wrong sessions in last 7 days
            week_ago = datetime.now() - timedelta(days=7)
            wrong_sessions_count = (
                db.session.query(func.count(Attendance.id))
                .filter(
                    and_(
                        Attendance.participant_id == participant_id,
                        Attendance.timestamp >= week_ago,
                        Attendance.is_correct_session == False,
                        Attendance.status == 'present'
                    )
                )
                .scalar()
            )

            if wrong_sessions_count > 0:
                warnings.append({
                    'type': 'wrong_sessions',
                    'message': f'You attended {wrong_sessions_count} wrong session(s) this week',
                    'severity': 'warning'
                })

            # Combine all data
            dashboard_data = profile_result
            dashboard_data['attendance'] = attendance_result
            dashboard_data['recent_attendance'] = recent_records
            dashboard_data['warnings'] = warnings

            logger.info(f"Retrieved dashboard data for participant {participant.unique_id}")
            return dashboard_data

        except Exception as e:
            logger.error(f"Error retrieving dashboard data: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving dashboard data'
            }

    # ===============================
    # PROFILE PHOTO MANAGEMENT (Mirror QR Code Strategy)
    # ===============================

    @staticmethod
    def upload_profile_photo(participant_id, photo_file, requesting_user_id):
        """
        Upload profile photo using identical QR code service strategy.

        Args:
            participant_id: Participant ID
            photo_file: Uploaded file object
            requesting_user_id: ID of user uploading

        Returns:
            dict: Upload result with photo URL
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get participant and validate permissions
            participant = (
                db.session.query(Participant)
                .options(joinedload(Participant.user))
                .filter_by(id=participant_id)
                .first()
            )

            if not participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PARTICIPANT_NOT_FOUND,
                    'message': 'Participant not found'
                }

            # Permission check (own profile only)
            if participant.user_id != requesting_user_id:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Can only upload to own profile'
                }

            # Validate file type (mirror QR code validation)
            if not photo_file or not photo_file.filename:
                return {
                    'success': False,
                    'error_code': ParticipantsError.INVALID_FILE_TYPE,
                    'message': 'No file selected'
                }

            # Check file extension
            allowed_extensions = {'jpg', 'jpeg', 'png', 'webp'}
            file_ext = photo_file.filename.rsplit('.', 1)[1].lower() if '.' in photo_file.filename else ''

            if file_ext not in allowed_extensions:
                return {
                    'success': False,
                    'error_code': ParticipantsError.INVALID_FILE_TYPE,
                    'message': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'
                }

            # Check file size (2MB limit)
            photo_file.seek(0, 2)  # Seek to end
            file_size = photo_file.tell()
            photo_file.seek(0)  # Reset to beginning

            max_size = 2 * 1024 * 1024  # 2MB
            if file_size > max_size:
                return {
                    'success': False,
                    'error_code': ParticipantsError.INVALID_FILE_TYPE,
                    'message': 'File too large. Maximum size: 2MB'
                }

            # Create profile photos directory (mirror QR code approach)
            photos_folder = os.path.join(current_app.config['BASE_DIR'], 'static', 'profile_photos')
            os.makedirs(photos_folder, exist_ok=True)

            # Generate secure filename (exactly like QR code service)
            secure_token = secrets.token_urlsafe(12)
            filename = f"{participant_id}_{secure_token}.{file_ext}"
            file_path = os.path.join(photos_folder, filename)

            # Delete existing photo if it exists
            if hasattr(participant, 'profile_photo_path') and participant.profile_photo_path:
                ParticipantsService._cleanup_profile_photo(participant.profile_photo_path)

            # Save file
            photo_file.save(file_path)

            # Update participant record (add field to model if not exists)
            if not hasattr(participant, 'profile_photo_path'):
                # This would require a migration to add the field
                logger.warning("profile_photo_path field not found in Participant model")
                return {
                    'success': False,
                    'error_code': ParticipantsError.REQUEST_FAILED,
                    'message': 'Profile photo feature not available'
                }

            participant.profile_photo_path = file_path
            db.session.commit()

            # Generate URL for display
            photo_url = ParticipantsService._get_profile_photo_url(file_path)

            logger.info(f"Profile photo uploaded for participant {participant.unique_id}")
            return {
                'success': True,
                'message': 'Profile photo uploaded successfully',
                'photo_url': photo_url,
                'filename': filename
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error uploading profile photo: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.FILE_UPLOAD_FAILED,
                'message': 'Error uploading photo'
            }

    # ===============================
    # ATTENDANCE ANALYTICS (Use Existing Service)
    # ===============================

    @staticmethod
    def get_attendance_summary(participant_id, requesting_user_id, date_range=None):
        """
        Get attendance summary using existing AttendanceService.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting data
            date_range: Optional tuple of (start_date, end_date)

        Returns:
            dict: Attendance summary data
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            # Call existing attendance service
            return AttendanceService.get_participant_attendance_summary(
                participant_id=participant_id,
                date_range=date_range,
                include_sessions=True
            )

        except Exception as e:
            logger.error(f"Error retrieving attendance summary: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving attendance data'
            }

    @staticmethod
    def get_attendance_history(participant_id, requesting_user_id, limit=50, page=1):
        """
        Get paginated attendance history with optimized queries.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting data
            limit: Records per page
            page: Page number (1-based)

        Returns:
            dict: Paginated attendance history
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            offset = (page - 1) * limit

            # Get total count
            total_count = (
                db.session.query(func.count(Attendance.id))
                .filter_by(participant_id=participant_id)
                .scalar()
            )

            # Get paginated records
            attendance_records = (
                db.session.query(Attendance)
                .options(joinedload(Attendance.session))
                .filter_by(participant_id=participant_id)
                .order_by(desc(Attendance.timestamp))
                .limit(limit)
                .offset(offset)
                .all()
            )

            # Format records
            records = []
            for record in attendance_records:
                records.append({
                    'id': record.id,
                    'date': record.timestamp.strftime('%Y-%m-%d'),
                    'time': record.timestamp.strftime('%H:%M:%S'),
                    'session': {
                        'id': record.session.id,
                        'time_slot': record.session.time_slot,
                        'day': record.session.day
                    },
                    'status': record.status,
                    'is_correct_session': record.is_correct_session,
                    'check_in_method': record.check_in_method
                })

            return {
                'success': True,
                'records': records,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total_count,
                    'pages': (total_count + limit - 1) // limit
                }
            }

        except Exception as e:
            logger.error(f"Error retrieving attendance history: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving attendance history'
            }

    # ===============================
    # SESSION REASSIGNMENT (Use Existing Service)
    # ===============================

    @staticmethod
    def submit_reassignment_request(participant_id, day_type, requested_session_id, reason, requesting_user_id):
        """
        Submit session reassignment request using existing service.

        Args:
            participant_id: Participant ID
            day_type: 'Saturday' or 'Sunday'
            requested_session_id: Target session ID
            reason: Reason for reassignment
            requesting_user_id: ID of user making request

        Returns:
            dict: Request submission result
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check (own requests only)
            participant = (
                db.session.query(Participant)
                .options(joinedload(Participant.user))
                .filter_by(id=participant_id)
                .first()
            )

            if not participant or participant.user_id != requesting_user_id:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Can only request reassignment for own sessions'
                }

            # Call existing service
            return SessionClassroomService.create_reassignment_request(
                participant_id=participant_id,
                day_type=day_type,
                requested_session_id=requested_session_id,
                reason=reason
            )

        except Exception as e:
            logger.error(f"Error submitting reassignment request: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error submitting reassignment request'
            }

    @staticmethod
    def get_reassignment_history(participant_id, requesting_user_id, limit=20):
        """
        Get reassignment history using existing service.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting data
            limit: Maximum number of records

        Returns:
            dict: Reassignment history
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            # Call existing service
            history = SessionClassroomService.get_participant_reassignment_history(
                participant_id=participant_id,
                limit=limit
            )

            return {
                'success': True,
                'requests': history
            }

        except Exception as e:
            logger.error(f"Error retrieving reassignment history: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving reassignment history'
            }

    # ===============================
    # STUDENT REPRESENTATIVE FEATURES
    # ===============================

    @staticmethod
    def get_session_participants(requesting_user_id, session_id=None, day_type=None):
        """
        Get participants in same sessions as student representative.
        Student reps can access students in the SAME SESSIONS they are in.

        Args:
            requesting_user_id: Student representative user ID
            session_id: Optional specific session ID
            day_type: Optional day filter ('Saturday' or 'Sunday')

        Returns:
            dict: List of participants in same sessions
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get requesting user with participant data
            requesting_user = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant).joinedload(Participant.saturday_session),
                    joinedload(User.participant).joinedload(Participant.sunday_session)
                )
                .filter_by(id=requesting_user_id)
                .first()
            )

            if not requesting_user or not requesting_user.participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Invalid user or no participant record'
                }

            # Check if user is student representative
            if not requesting_user.has_role(RoleType.STUDENT_REPRESENTATIVE):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Student representative role required'
                }

            rep_participant = requesting_user.participant
            session_ids = []

            # Get session IDs that the student rep is in
            if day_type == 'Saturday' and rep_participant.saturday_session_id:
                session_ids = [rep_participant.saturday_session_id]
            elif day_type == 'Sunday' and rep_participant.sunday_session_id:
                session_ids = [rep_participant.sunday_session_id]
            elif session_id:
                # Validate that the student rep is in this session
                if session_id in [rep_participant.saturday_session_id, rep_participant.sunday_session_id]:
                    session_ids = [session_id]
                else:
                    return {
                        'success': False,
                        'error_code': ParticipantsError.PERMISSION_DENIED,
                        'message': 'Can only access participants in your own sessions'
                    }
            else:
                # Get both sessions if no filter
                if rep_participant.saturday_session_id:
                    session_ids.append(rep_participant.saturday_session_id)
                if rep_participant.sunday_session_id:
                    session_ids.append(rep_participant.sunday_session_id)

            if not session_ids:
                return {
                    'success': True,
                    'participants': [],
                    'message': 'No sessions assigned'
                }

            # Get participants in same sessions (optimized query)
            participants = (
                db.session.query(Participant)
                .options(
                    joinedload(Participant.user),
                    joinedload(Participant.saturday_session),
                    joinedload(Participant.sunday_session)
                )
                .filter(
                    or_(
                        Participant.saturday_session_id.in_(session_ids),
                        Participant.sunday_session_id.in_(session_ids)
                    )
                )
                .order_by(Participant.surname, Participant.first_name)
                .all()
            )

            # Format participant data
            participant_list = []
            for participant in participants:
                # Skip the requesting user themselves
                if participant.id == rep_participant.id:
                    continue

                participant_data = {
                    'id': participant.id,
                    'unique_id': participant.unique_id,
                    'full_name': participant.full_name,
                    'email': participant.email,
                    'has_laptop': participant.has_laptop,
                    'classroom': participant.classroom,
                    'consecutive_missed_sessions': participant.consecutive_missed_sessions,
                    'is_active': participant.user.is_active if participant.user else False,
                    'sessions': {
                        'saturday': participant.saturday_session.time_slot if participant.saturday_session else None,
                        'sunday': participant.sunday_session.time_slot if participant.sunday_session else None
                    }
                }
                participant_list.append(participant_data)

            return {
                'success': True,
                'participants': participant_list,
                'session_info': {
                    'saturday_session': rep_participant.saturday_session.time_slot if rep_participant.saturday_session else None,
                    'sunday_session': rep_participant.sunday_session.time_slot if rep_participant.sunday_session else None
                }
            }

        except Exception as e:
            logger.error(f"Error retrieving session participants: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving session participants'
            }

    @staticmethod
    def mark_attendance_for_participant(target_participant_id, session_id, requesting_user_id, status='present'):
        """
        Mark attendance for another participant (student rep only).

        Args:
            target_participant_id: Participant to mark attendance for
            session_id: Session ID
            requesting_user_id: Student representative user ID
            status: Attendance status ('present', 'absent', 'late')

        Returns:
            dict: Attendance marking result
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get requesting user
            requesting_user = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant)
                )
                .filter_by(id=requesting_user_id)
                .first()
            )

            if not requesting_user or not requesting_user.participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Invalid user'
                }

            # Check permissions
            if not requesting_user.has_permission(Permission.MARK_ATTENDANCE):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Permission denied to mark attendance'
                }

            # Get target participant
            target_participant = db.session.query(Participant).filter_by(id=target_participant_id).first()
            if not target_participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PARTICIPANT_NOT_FOUND,
                    'message': 'Target participant not found'
                }

            # Validate that requesting user can access this participant
            if not PermissionChecker.can_view_participant(requesting_user, target_participant):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Can only mark attendance for participants in your sessions'
                }

            # Use existing attendance service for verification and recording
            return AttendanceService.verify_and_record_attendance(
                unique_id=target_participant.unique_id,
                session_identifier=session_id,
                check_in_method='manual_rep',
                admin_user_id=requesting_user_id,
                force_record=True  # Allow manual marking
            )

        except Exception as e:
            logger.error(f"Error marking attendance: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error marking attendance'
            }

    # ===============================
    # HELPER METHODS (Mirror QR Code Service)
    # ===============================

    @staticmethod
    def _get_profile_photo_url(photo_path):
        """
        Convert profile photo path to static URL (mirror QR code approach).

        Args:
            photo_path: File system path to photo

        Returns:
            str: Static URL for the photo
        """
        try:
            if not photo_path:
                return None

            filename = os.path.basename(photo_path)
            return url_for('static', filename=f'profile_photos/{filename}')

        except Exception as e:
            logging.getLogger('participants_service').error(f"Error building photo URL: {str(e)}")
            return None

    @staticmethod
    def _cleanup_profile_photo(photo_path):
        """
        Safely delete profile photo file (mirror QR code approach).

        Args:
            photo_path: File system path to photo
        """
        try:
            if photo_path and os.path.isfile(photo_path):
                os.remove(photo_path)
                logging.getLogger('participants_service').info(f"Deleted profile photo: {photo_path}")
        except Exception as e:
            logging.getLogger('participants_service').error(f"Error deleting photo: {str(e)}")

    @staticmethod
    def _validate_profile_photo(photo_path):
        """
        Check if profile photo exists and is readable (mirror QR code approach).

        Args:
            photo_path: File system path to photo

        Returns:
            bool: True if photo exists and is valid
        """
        try:
            return photo_path and os.path.isfile(photo_path) and os.access(photo_path, os.R_OK)
        except Exception:
            return False


    @staticmethod
    def delete_profile_photo(participant_id, requesting_user_id):
        """
        Delete profile photo and cleanup file.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting deletion

        Returns:
            dict: Deletion result
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check (own profile only)
            participant = (
                db.session.query(Participant)
                .options(joinedload(Participant.user))
                .filter_by(id=participant_id)
                .first()
            )

            if not participant or participant.user_id != requesting_user_id:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Can only delete own profile photo'
                }

            # Check if photo exists
            if not hasattr(participant, 'profile_photo_path') or not participant.profile_photo_path:
                return {
                    'success': False,
                    'error_code': ParticipantsError.REQUEST_FAILED,
                    'message': 'No profile photo to delete'
                }

            # Delete file and clear path
            photo_path = participant.profile_photo_path
            ParticipantsService._cleanup_profile_photo(photo_path)

            participant.profile_photo_path = None
            db.session.commit()

            logger.info(f"Profile photo deleted for participant {participant.unique_id}")
            return {
                'success': True,
                'message': 'Profile photo deleted successfully'
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting profile photo: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error deleting profile photo'
            }


    @staticmethod
    def get_attendance_issues(participant_id, requesting_user_id):
        """
        Get attendance issues and warnings for participant.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting data

        Returns:
            dict: Attendance issues data
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            participant = db.session.query(Participant).filter_by(id=participant_id).first()
            issues = []

            # Consecutive absences warning
            if participant.consecutive_missed_sessions >= 2:
                severity = 'danger' if participant.consecutive_missed_sessions >= 3 else 'warning'
                issues.append({
                    'type': 'consecutive_absences',
                    'title': 'Consecutive Absences',
                    'message': f'You have missed {participant.consecutive_missed_sessions} consecutive sessions',
                    'severity': severity,
                    'count': participant.consecutive_missed_sessions,
                    'action_required': participant.consecutive_missed_sessions >= 3
                })

            # Wrong sessions in last 30 days
            thirty_days_ago = datetime.now() - timedelta(days=30)
            wrong_sessions_count = (
                db.session.query(func.count(Attendance.id))
                .filter(
                    and_(
                        Attendance.participant_id == participant_id,
                        Attendance.timestamp >= thirty_days_ago,
                        Attendance.is_correct_session == False,
                        Attendance.status == 'present'
                    )
                )
                .scalar()
            )

            if wrong_sessions_count > 0:
                issues.append({
                    'type': 'wrong_sessions',
                    'title': 'Wrong Session Attendance',
                    'message': f'You attended {wrong_sessions_count} wrong session(s) in the last 30 days',
                    'severity': 'warning' if wrong_sessions_count <= 2 else 'danger',
                    'count': wrong_sessions_count,
                    'action_required': wrong_sessions_count > 2
                })

            # Account status warning
            if participant.user and not participant.user.is_active:
                issues.append({
                    'type': 'account_inactive',
                    'title': 'Account Inactive',
                    'message': 'Your account has been deactivated due to excessive absences',
                    'severity': 'danger',
                    'action_required': True
                })

            return {
                'success': True,
                'issues': issues,
                'has_critical_issues': any(issue['severity'] == 'danger' for issue in issues)
            }

        except Exception as e:
            logger.error(f"Error retrieving attendance issues: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving attendance issues'
            }


    @staticmethod
    def get_attendance_calendar_data(participant_id, requesting_user_id, month=None, year=None):
        """
        Get attendance data formatted for calendar view.

        Args:
            participant_id: Participant ID
            requesting_user_id: ID of user requesting data
            month: Month (1-12)
            year: Year (YYYY)

        Returns:
            dict: Calendar attendance data
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            # Default to current month/year
            if not month or not year:
                now = datetime.now()
                month = month or now.month
                year = year or now.year

            # Get month boundaries
            start_date = datetime(year, month, 1).date()
            last_day = calendar.monthrange(year, month)[1]
            end_date = datetime(year, month, last_day).date()

            # Get attendance records for month (optimized query)
            attendance_records = (
                db.session.query(Attendance)
                .options(joinedload(Attendance.session))
                .filter(
                    and_(
                        Attendance.participant_id == participant_id,
                        func.date(Attendance.timestamp) >= start_date,
                        func.date(Attendance.timestamp) <= end_date
                    )
                )
                .order_by(Attendance.timestamp)
                .all()
            )

            # Format calendar data
            calendar_data = {}
            for record in attendance_records:
                date_key = record.timestamp.strftime('%Y-%m-%d')

                if date_key not in calendar_data:
                    calendar_data[date_key] = []

                calendar_data[date_key].append({
                    'session': record.session.time_slot,
                    'day': record.session.day,
                    'status': record.status,
                    'is_correct_session': record.is_correct_session,
                    'time': record.timestamp.strftime('%H:%M')
                })

            # Calculate month statistics
            total_records = len(attendance_records)
            present_records = sum(1 for r in attendance_records if r.status == 'present')
            correct_sessions = sum(1 for r in attendance_records if r.is_correct_session and r.status == 'present')

            month_stats = {
                'total_sessions': total_records,
                'present_sessions': present_records,
                'correct_sessions': correct_sessions,
                'attendance_rate': round((present_records / total_records) * 100, 1) if total_records > 0 else 0,
                'correct_session_rate': round((correct_sessions / present_records) * 100, 1) if present_records > 0 else 0
            }

            return {
                'success': True,
                'calendar_data': calendar_data,
                'month_stats': month_stats,
                'month': month,
                'year': year,
                'month_name': calendar.month_name[month]
            }

        except Exception as e:
            logger.error(f"Error retrieving calendar data: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving calendar data'
            }


    @staticmethod
    def get_available_sessions_for_reassignment(participant_id, day_type, requesting_user_id):
        """
        Get available sessions for reassignment by day type.

        Args:
            participant_id: Participant ID
            day_type: 'Saturday' or 'Sunday'
            requesting_user_id: ID of user requesting data

        Returns:
            dict: Available sessions data
        """
        logger = logging.getLogger('participants_service')

        try:
            # Permission check
            profile_result = ParticipantsService.get_participant_profile(participant_id, requesting_user_id)
            if not profile_result['success']:
                return profile_result

            participant = db.session.query(Participant).filter_by(id=participant_id).first()

            # Get current session for this day
            current_session_id = (
                participant.saturday_session_id if day_type == 'Saturday'
                else participant.sunday_session_id
            )

            # Get all sessions for the day
            sessions = (
                db.session.query(Session)
                .filter_by(day=day_type)
                .order_by(Session.time_slot)
                .all()
            )

            # Format available sessions (exclude current session)
            available_sessions = []
            for session in sessions:
                if session.id == current_session_id:
                    continue

                # Get current capacity using existing service
                current_count = SessionClassroomService.get_session_participant_count(
                    session.id, participant.classroom, day_type
                )
                capacity = SessionClassroomService.get_classroom_capacity(participant.classroom)

                available_sessions.append({
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'day': session.day,
                    'current_capacity': current_count,
                    'max_capacity': capacity,
                    'available_spots': max(0, capacity - current_count),
                    'is_full': current_count >= capacity
                })

            # Get current session info
            current_session = db.session.query(Session).filter_by(id=current_session_id).first()
            current_session_info = {
                'id': current_session.id,
                'time_slot': current_session.time_slot,
                'day': current_session.day
            } if current_session else None

            return {
                'success': True,
                'available_sessions': available_sessions,
                'current_session': current_session_info,
                'day_type': day_type
            }

        except Exception as e:
            logger.error(f"Error retrieving available sessions: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving available sessions'
            }


    @staticmethod
    def get_reassignment_request_status(request_id, requesting_user_id):
        """
        Get status of specific reassignment request.

        Args:
            request_id: Request ID
            requesting_user_id: ID of user requesting data

        Returns:
            dict: Request status data
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get request with related data
            request = (
                db.session.query(SessionReassignmentRequest)
                .options(
                    joinedload(SessionReassignmentRequest.participant),
                    joinedload(SessionReassignmentRequest.current_session),
                    joinedload(SessionReassignmentRequest.requested_session)
                )
                .filter_by(id=request_id)
                .first()
            )

            if not request:
                return {
                    'success': False,
                    'error_code': ParticipantsError.REQUEST_FAILED,
                    'message': 'Request not found'
                }

            # Permission check (own requests only)
            if request.participant.user_id != requesting_user_id:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Access denied'
                }

            return {
                'success': True,
                'request': {
                    'id': request.id,
                    'day_type': request.day_type,
                    'current_session': request.current_session.time_slot,
                    'requested_session': request.requested_session.time_slot,
                    'reason': request.reason,
                    'status': request.status,
                    'admin_notes': request.admin_notes,
                    'created_at': request.created_at.isoformat(),
                    'reviewed_at': request.reviewed_at.isoformat() if request.reviewed_at else None
                }
            }

        except Exception as e:
            logger.error(f"Error retrieving request status: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving request status'
            }


    @staticmethod
    def get_representative_session_info(requesting_user_id):
        """
        Get session information for student representative.

        Args:
            requesting_user_id: Student representative user ID

        Returns:
            dict: Representative's session information
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get requesting user with participant data
            requesting_user = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant).joinedload(Participant.saturday_session),
                    joinedload(User.participant).joinedload(Participant.sunday_session)
                )
                .filter_by(id=requesting_user_id)
                .first()
            )

            if not requesting_user or not requesting_user.participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Invalid user or no participant record'
                }

            # Check if user is student representative
            if not requesting_user.has_role(RoleType.STUDENT_REPRESENTATIVE):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Student representative role required'
                }

            rep_participant = requesting_user.participant

            return {
                'success': True,
                'data': {
                    'representative': {
                        'id': rep_participant.id,
                        'unique_id': rep_participant.unique_id,
                        'full_name': rep_participant.full_name,
                        'classroom': rep_participant.classroom
                    },
                    'sessions': {
                        'saturday': {
                            'id': rep_participant.saturday_session.id if rep_participant.saturday_session else None,
                            'time_slot': rep_participant.saturday_session.time_slot if rep_participant.saturday_session else None,
                            'day': 'Saturday'
                        },
                        'sunday': {
                            'id': rep_participant.sunday_session.id if rep_participant.sunday_session else None,
                            'time_slot': rep_participant.sunday_session.time_slot if rep_participant.sunday_session else None,
                            'day': 'Sunday'
                        }
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error retrieving representative session info: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving session information'
            }


    @staticmethod
    def get_student_contact_info(student_id, requesting_user_id):
        """
        Get student contact information for representative access.

        Args:
            student_id: Student participant ID
            requesting_user_id: Student representative user ID

        Returns:
            dict: Student contact information
        """
        logger = logging.getLogger('participants_service')

        try:
            # Get requesting user
            requesting_user = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant)
                )
                .filter_by(id=requesting_user_id)
                .first()
            )

            if not requesting_user or not requesting_user.participant:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Invalid user'
                }

            # Check permissions
            if not requesting_user.has_role(RoleType.STUDENT_REPRESENTATIVE):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Student representative role required'
                }

            # Get student
            student = db.session.query(Participant).filter_by(id=student_id).first()
            if not student:
                return {
                    'success': False,
                    'error_code': ParticipantsError.PARTICIPANT_NOT_FOUND,
                    'message': 'Student not found'
                }

            # Validate that requesting user can access this student
            if not PermissionChecker.can_view_participant(requesting_user, student):
                return {
                    'success': False,
                    'error_code': ParticipantsError.PERMISSION_DENIED,
                    'message': 'Can only access students in your sessions'
                }

            return {
                'success': True,
                'student': {
                    'id': student.id,
                    'unique_id': student.unique_id,
                    'full_name': student.full_name,
                    'email': student.email,
                    'phone': student.phone,
                    'classroom': student.classroom
                }
            }

        except Exception as e:
            logger.error(f"Error retrieving student contact info: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error_code': ParticipantsError.REQUEST_FAILED,
                'message': 'Error retrieving student contact information'
            }
