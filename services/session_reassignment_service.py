# services/session_reassignment_service.py
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from ..extensions import db
from ..models import Participant, Session, SessionReassignmentRequest, ReassignmentStatus
from ..utils.session_mapper import get_session_count, get_session_capacity
from datetime import datetime


class SessionReassignmentService:
    def get_available_sessions(self, day, participant_has_laptop):
        """
        Get all available sessions for a specific day with capacity information
        """
        try:
            # Get all sessions for the day
            sessions = Session.query.filter_by(day=day).all()

            # Determine classroom based on laptop status
            classroom = current_app.config['LAPTOP_CLASSROOM'] if participant_has_laptop else current_app.config[
                'NO_LAPTOP_CLASSROOM']

            # Build response with capacity info
            result = []
            for session in sessions:
                # Calculate capacity info
                total_capacity = get_session_capacity(classroom)
                current_count = get_session_count(session.id, classroom)
                available = total_capacity - current_count
                percentage_filled = round((current_count / total_capacity) * 100, 1) if total_capacity > 0 else 0

                result.append({
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'capacity': {
                        'total': total_capacity,
                        'used': current_count,
                        'available': available,
                        'percentage_filled': percentage_filled
                    },
                    'has_capacity': available > 0
                })

            return {
                'success': True,
                'sessions': result
            }

        except Exception as e:
            current_app.logger.error(f"Error getting available sessions: {str(e)}")
            return {
                'success': False,
                'message': f"An error occurred: {str(e)}",
                'error_code': 'session_fetch_error'
            }

    def create_reassignment_request(self, participant_id, data):
        """
        Create a new reassignment request

        Args:
            participant_id: ID of the participant making the request
            data: Dictionary containing request details
                {
                    'day_type': 'Saturday'/'Sunday',
                    'requested_session_id': session_id,
                    'reason': 'Reason for change'
                }
        """
        try:
            # Get participant
            participant = Participant.query.get(participant_id)
            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': 'participant_not_found'
                }

            # Check if participant has reached the maximum number of reassignments
            if participant.reassignments_count >= 2:
                return {
                    'success': False,
                    'message': 'Maximum number of reassignments (2) reached',
                    'error_code': 'max_reassignments_reached'
                }

            # Get the day type and current session ID
            day_type = data.get('day_type')
            if not day_type or day_type not in ['Saturday', 'Sunday']:
                return {
                    'success': False,
                    'message': 'Invalid day type. Must be Saturday or Sunday',
                    'error_code': 'invalid_day_type'
                }

            # Get current session ID based on day type
            current_session_id = participant.saturday_session_id if day_type == 'Saturday' else participant.sunday_session_id

            # Get requested session
            requested_session_id = data.get('requested_session_id')
            requested_session = Session.query.get(requested_session_id)

            if not requested_session:
                return {
                    'success': False,
                    'message': 'Requested session not found',
                    'error_code': 'session_not_found'
                }

            # Validate requested session day matches day_type
            if requested_session.day != day_type:
                return {
                    'success': False,
                    'message': f'Requested session is not a {day_type} session',
                    'error_code': 'session_day_mismatch'
                }

            # Check if the same session is requested
            if current_session_id == requested_session_id:
                return {
                    'success': False,
                    'message': 'Cannot request reassignment to the same session',
                    'error_code': 'same_session_requested'
                }

            # Check for capacity in the requested session
            classroom = current_app.config['LAPTOP_CLASSROOM'] if participant.has_laptop else current_app.config[
                'NO_LAPTOP_CLASSROOM']
            total_capacity = get_session_capacity(classroom)
            current_count = get_session_count(requested_session_id, classroom)

            if current_count >= total_capacity:
                return {
                    'success': False,
                    'message': 'Requested session has no available capacity',
                    'error_code': 'session_at_capacity'
                }

            # Check for existing pending request for the same day
            existing_request = SessionReassignmentRequest.query.filter_by(
                participant_id=participant_id,
                day_type=day_type,
                status=ReassignmentStatus.PENDING
            ).first()

            if existing_request:
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
                reason=data.get('reason', '')
            )

            db.session.add(new_request)
            db.session.commit()

            return {
                'success': True,
                'message': 'Reassignment request submitted successfully',
                'request_id': new_request.id
            }

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error creating reassignment request: {str(e)}")
            return {
                'success': False,
                'message': 'Database error occurred',
                'error_code': 'database_error'
            }
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error creating reassignment request: {str(e)}")
            return {
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}',
                'error_code': 'unexpected_error'
            }

    def get_participant_requests(self, participant_id):
        """Get all reassignment requests for a participant"""
        try:
            requests = SessionReassignmentRequest.query.filter_by(participant_id=participant_id).order_by(
                SessionReassignmentRequest.created_at.desc()).all()

            result = []
            for req in requests:
                result.append({
                    'id': req.id,
                    'day_type': req.day_type,
                    'current_session': req.current_session.time_slot,
                    'requested_session': req.requested_session.time_slot,
                    'reason': req.reason,
                    'status': req.status,
                    'admin_notes': req.admin_notes,
                    'created_at': req.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': req.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                })

            return {
                'success': True,
                'requests': result
            }

        except Exception as e:
            current_app.logger.error(f"Error getting participant requests: {str(e)}")
            return {
                'success': False,
                'message': f"An error occurred: {str(e)}",
                'error_code': 'request_fetch_error'
            }

    def get_pending_requests(self):
        """Get all pending reassignment requests for admin review"""
        try:
            requests = SessionReassignmentRequest.query.filter_by(status=ReassignmentStatus.PENDING).order_by(
                SessionReassignmentRequest.created_at.asc()).all()

            result = []
            for req in requests:
                participant = req.participant

                result.append({
                    'id': req.id,
                    'participant': {
                        'id': participant.id,
                        'name': participant.name,
                        'unique_id': participant.unique_id,
                        'email': participant.email,
                        'has_laptop': participant.has_laptop,
                        'classroom': participant.classroom,
                        'reassignments_count': participant.reassignments_count
                    },
                    'day_type': req.day_type,
                    'current_session': req.current_session.time_slot,
                    'requested_session': req.requested_session.time_slot,
                    'reason': req.reason,
                    'created_at': req.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })

            return {
                'success': True,
                'requests': result
            }

        except Exception as e:
            current_app.logger.error(f"Error getting pending requests: {str(e)}")
            return {
                'success': False,
                'message': f"An error occurred: {str(e)}",
                'error_code': 'request_fetch_error'
            }

    def process_reassignment_request(self, request_id, admin_id, approve, admin_notes=None):
        """
        Process (approve or reject) a reassignment request

        Args:
            request_id: ID of the request to process
            admin_id: ID of the admin processing the request
            approve: Boolean indicating approval (True) or rejection (False)
            admin_notes: Optional notes from the admin
        """
        try:
            # Get the request
            request = SessionReassignmentRequest.query.get(request_id)
            if not request:
                return {
                    'success': False,
                    'message': 'Reassignment request not found',
                    'error_code': 'request_not_found'
                }

            # Check if request is already processed
            if request.status != ReassignmentStatus.PENDING:
                return {
                    'success': False,
                    'message': f'Request has already been {request.status}',
                    'error_code': 'request_already_processed'
                }

            # Update request status and add admin info
            request.status = ReassignmentStatus.APPROVED if approve else ReassignmentStatus.REJECTED
            request.admin_notes = admin_notes
            request.reviewed_at = datetime.utcnow()
            request.reviewed_by = admin_id

            # If approved, update the participant's session assignment and increment reassignment count
            if approve:
                participant = request.participant

                # Check if the requested session still has capacity
                classroom = participant.classroom
                total_capacity = get_session_capacity(classroom)
                current_count = get_session_count(request.requested_session_id, classroom)

                if current_count >= total_capacity:
                    return {
                        'success': False,
                        'message': 'Requested session no longer has available capacity',
                        'error_code': 'session_now_at_capacity'
                    }

                # Update the participant's session
                if request.day_type == 'Saturday':
                    participant.saturday_session_id = request.requested_session_id
                else:
                    participant.sunday_session_id = request.requested_session_id

                # Increment reassignment count
                participant.reassignments_count += 1

            # Commit changes
            db.session.commit()

            return {
                'success': True,
                'message': f'Request has been {"approved" if approve else "rejected"}',
                'request_id': request.id,
                'status': request.status
            }

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error processing reassignment request: {str(e)}")
            return {
                'success': False,
                'message': 'Database error occurred',
                'error_code': 'database_error'
            }
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error processing reassignment request: {str(e)}")
            return {
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}',
                'error_code': 'unexpected_error'
            }
