# utils/auth.py
from functools import wraps
from flask import request, jsonify, current_app
from flask_login import current_user
from app.models import Permission, RoleType


def permission_required(permission):
    """Decorator to require specific permission."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401

            if not current_user.has_permission(permission):
                return jsonify({'error': 'Insufficient permissions'}), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def role_required(*roles):
    """Decorator to require specific role(s)."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401

            if not current_user.has_any_role(roles):
                return jsonify({'error': f'Role required: {", ".join(roles)}'}), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def staff_required(f):
    """Decorator to require staff role (teacher, chaplain, or admin)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        if not current_user.is_staff():
            return jsonify({'error': 'Staff access required'}), 403

        return f(*args, **kwargs)

    return decorated_function


def student_or_staff_required(f):
    """Decorator that allows both students and staff."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        return f(*args, **kwargs)

    return decorated_function


class PermissionChecker:
    """Utility class for complex permission checks."""

    @staticmethod
    def can_view_participant(user, participant):
        """Check if user can view specific participant."""
        # Staff can view all participants
        if user.is_staff():
            return True

        # Students can only view themselves
        if user.is_student() and user.participant_id == participant.id:
            return True

        # Student representatives can view participants in same classroom
        if user.has_role(RoleType.STUDENT_REPRESENTATIVE) and user.participant:
            return user.participant.classroom == participant.classroom

        return False

    @staticmethod
    def can_edit_participant(user, participant):
        """Check if user can edit specific participant."""
        # Only staff can edit participant records
        if not user.is_staff():
            return False

        # Teachers can edit participants in their sessions
        if user.has_role(RoleType.TEACHER):
            # Check if teacher has any sessions with this participant
            return PermissionChecker._teacher_has_participant(user, participant)

        # Chaplains and admins can edit all
        return user.has_any_role([RoleType.CHAPLAIN, RoleType.ADMIN])

    @staticmethod
    def can_mark_attendance(user, session):
        """Check if user can mark attendance for specific session."""
        # Staff with permission can mark any session
        if user.is_staff() and user.has_permission(Permission.MARK_ATTENDANCE):
            return True

        # Student representatives can mark attendance for their classroom sessions
        if user.has_role(RoleType.STUDENT_REPRESENTATIVE) and user.participant:
            # Check if this session has participants from their classroom
            return PermissionChecker._session_has_classroom(session, user.participant.classroom)

        return False

    @staticmethod
    def can_approve_reassignment(user, reassignment_request):
        """Check if user can approve specific reassignment request."""
        if not user.has_permission(Permission.APPROVE_REASSIGNMENTS):
            return False

        # Teachers can only approve requests for their students
        if user.has_role(RoleType.TEACHER):
            return PermissionChecker._teacher_has_participant(user, reassignment_request.participant)

        # Chaplains and admins can approve all
        return user.has_any_role([RoleType.CHAPLAIN, RoleType.ADMIN])

    @staticmethod
    def _teacher_has_participant(teacher_user, participant):
        """Check if teacher has this participant in any of their sessions."""
        # This would need to be implemented based on how you track teacher-session assignments
        # For now, assuming all teachers can manage all participants
        return True

    @staticmethod
    def _session_has_classroom(session, classroom):
        """Check if session has participants from specific classroom."""
        # Check Saturday participants
        saturday_match = any(
            p.classroom == classroom
            for p in session.saturday_participants
        )

        # Check Sunday participants
        sunday_match = any(
            p.classroom == classroom
            for p in session.sunday_participants
        )

        return saturday_match or sunday_match
