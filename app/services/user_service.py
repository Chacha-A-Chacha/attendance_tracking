# services/user_service.py
from flask import current_app
from sqlalchemy.orm import joinedload
from app.models.user import User, Role, RoleType, Permission
from app.models.participant import Participant
from app.extensions import db
import secrets


class UserService:
    """Service class for user management operations."""

    @staticmethod
    def create_user(username, email, first_name, last_name, password=None, roles=None):
        """Create a new user with specified roles (for non-participant users)."""
        # Check if user already exists
        if db.session.query(User.query.filter_by(username=username).exists()).scalar():
            raise ValueError(f"Username '{username}' already exists")

        if db.session.query(User.query.filter_by(email=email).exists()).scalar():
            raise ValueError(f"Email '{email}' already exists")

        # Generate password if not provided
        if not password:
            password = secrets.token_urlsafe(12)

        # Create user
        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        user.set_password(password)

        # Assign roles
        if roles:
            for role_name in roles:
                user.add_role(role_name)

        db.session.add(user)
        db.session.commit()

        return user, password

    @staticmethod
    def bulk_create_student_accounts():
        """Create user accounts for all participants without accounts."""
        # Query optimized: use exists subquery and eager load relationships
        participants_without_users = (
            db.session.query(Participant)
            .filter(~db.session.query(User.participant_id)
                    .filter(User.participant_id == Participant.id)
                    .exists())
            .all()
        )

        created_accounts = []

        try:
            for participant in participants_without_users:
                try:
                    user, password = participant.create_user_account()
                    db.session.flush()  # Get user ID without committing

                    created_accounts.append({
                        'participant': participant,
                        'user': user,
                        'username': user.username,
                        'password': password
                    })
                except Exception as e:
                    current_app.logger.error(
                        f"Failed to create account for participant {participant.id}: {e}"
                    )
                    db.session.rollback()
                    continue

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Bulk account creation failed: {e}")
            raise

        return created_accounts

    @staticmethod
    def promote_to_student_representative(user_id):
        """Promote a student to student representative."""
        # Query optimized: eager load participant and roles
        user = (
            db.session.query(User)
            .options(joinedload(User.participant), joinedload(User.roles))
            .filter_by(id=user_id)
            .first()
        )

        if not user:
            raise ValueError("User not found")

        if not user.is_student():
            raise ValueError("User must be a student")

        if user.has_role(RoleType.STUDENT_REPRESENTATIVE):
            raise ValueError("User is already a student representative")

        user.add_role(RoleType.STUDENT_REPRESENTATIVE)
        db.session.commit()

        return user

    @staticmethod
    def revoke_student_representative(user_id):
        """Revoke student representative role."""
        # Query optimized: eager load roles
        user = (
            db.session.query(User)
            .options(joinedload(User.roles))
            .filter_by(id=user_id)
            .first()
        )

        if not user:
            raise ValueError("User not found")

        user.remove_role(RoleType.STUDENT_REPRESENTATIVE)
        db.session.commit()

        return user

    @staticmethod
    def change_user_password(user_id, new_password, current_user=None):
        """Change user password with appropriate authorization."""
        # Query optimized: eager load roles for both users
        user = (
            db.session.query(User)
            .options(joinedload(User.roles))
            .filter_by(id=user_id)
            .first()
        )

        if not user:
            raise ValueError("User not found")

        # Check authorization
        if current_user:
            # Users can change their own password
            if current_user.id != user.id:
                # Or users with edit permission can change others' passwords
                if not current_user.has_permission(Permission.EDIT_USERS):
                    raise ValueError("Insufficient permissions")

                # Check role hierarchy
                if not current_user.can_manage_user(user):
                    raise ValueError("Cannot manage user with equal or higher role")

        user.set_password(new_password)
        db.session.commit()

        return user

    @staticmethod
    def get_users_by_role(role_name, include_inactive=False):
        """Get all users with a specific role (query optimized)."""
        query = (
            db.session.query(User)
            .join(User.roles)
            .filter(Role.name == role_name)
            .options(joinedload(User.roles), joinedload(User.participant))
        )

        if not include_inactive:
            query = query.filter(User.is_active == True)

        return query.all()

    @staticmethod
    def get_student_users(include_inactive=False):
        """Get all student users (participants with accounts)."""
        query = (
            db.session.query(User)
            .join(User.participant)
            .options(joinedload(User.roles), joinedload(User.participant))
        )

        if not include_inactive:
            query = query.filter(User.is_active == True)

        return query.all()

    @staticmethod
    def deactivate_user(user_id, deactivated_by=None):
        """Deactivate a user account."""
        user = db.session.query(User).filter_by(id=user_id).first()

        if not user:
            raise ValueError("User not found")

        user.is_active = False
        db.session.commit()

        return user

    @staticmethod
    def reactivate_user(user_id, reactivated_by=None):
        """Reactivate a user account."""
        user = db.session.query(User).filter_by(id=user_id).first()

        if not user:
            raise ValueError("User not found")

        user.is_active = True

        # If user is a student, also reset consecutive missed sessions
        if user.participant:
            user.participant.reactivate_user_account()

        db.session.commit()

        return user
