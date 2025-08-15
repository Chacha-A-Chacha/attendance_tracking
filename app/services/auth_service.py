# services/auth_service.py
"""
Authentication service for user authentication, password management, and security operations.
Handles login, logout, password reset, account management with proper email notifications.
"""

import logging
import secrets
from datetime import datetime, timedelta
from flask import current_app, request, session
from flask_login import login_user, logout_user, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from app.models.user import User, Role, RoleType
from app.models.participant import Participant
from app.extensions import db, email_service
from app.utils.enhanced_email import Priority


class AuthService:
    """Service class for authentication and user security operations."""

    @staticmethod
    def authenticate_user(identifier, password, remember_me=False):
        """
        Authenticate user with username/email and password.

        Args:
            identifier: Username or email address
            password: User password
            remember_me: Whether to remember login session

        Returns:
            tuple: (success: bool, user: User|None, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            # Optimized query: eager load roles and participant for authorization
            user = (
                db.session.query(User)
                .options(
                    joinedload(User.roles),
                    joinedload(User.participant)
                )
                .filter(
                    and_(
                        or_(
                            User.username == identifier,
                            User.email == identifier
                        ),
                        User.is_active == True
                    )
                )
                .first()
            )

            if not user:
                logger.warning(f"Login attempt with non-existent identifier: {identifier}")
                return False, None, "Invalid username/email or password"

            # Check if account is locked
            if user.is_locked():
                logger.warning(f"Login attempt on locked account: {user.username}")
                return False, None, f"Account is locked until {user.locked_until.strftime('%Y-%m-%d %H:%M:%S')}"

            # Verify password
            if not user.check_password(password):
                user.record_failed_login()
                db.session.commit()

                logger.warning(f"Failed login attempt for user: {user.username}")

                # Check if account got locked after this attempt
                if user.is_locked():
                    return False, None, "Too many failed attempts. Account has been locked for 30 minutes."
                else:
                    attempts_left = 5 - user.failed_login_attempts
                    return False, None, f"Invalid password. {attempts_left} attempts remaining."

            # Successful authentication
            user.record_login()
            db.session.commit()

            # Log user in with Flask-Login
            login_user(user, remember=remember_me)

            logger.info(f"Successful login for user: {user.username}")
            return True, user, "Login successful"

        except Exception as e:
            logger.error(f"Authentication error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, None, "An error occurred during login. Please try again."

    @staticmethod
    def logout_user_session():
        """
        Logout current user and clear session.

        Returns:
            bool: True if logout successful
        """
        logger = logging.getLogger('auth_service')

        try:
            if current_user.is_authenticated:
                username = current_user.username
                logout_user()
                session.clear()
                logger.info(f"User logged out: {username}")

            return True

        except Exception as e:
            logger.error(f"Logout error: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def initiate_password_reset(email_or_username):
        """
        Initiate password reset process by sending reset email.

        Args:
            email_or_username: Email address or username

        Returns:
            tuple: (success: bool, message: str, task_id: str|None)
        """
        logger = logging.getLogger('auth_service')

        try:
            # Find user by email or username - optimized query
            user = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter(
                    and_(
                        or_(
                            User.email == email_or_username,
                            User.username == email_or_username
                        ),
                        User.is_active == True
                    )
                )
                .first()
            )

            if not user:
                # Don't reveal whether user exists - security measure
                logger.warning(f"Password reset requested for non-existent user: {email_or_username}")
                return True, "If the email exists, a reset link has been sent.", None

            # Generate secure reset token
            reset_token = secrets.token_urlsafe(32)
            reset_expires = datetime.now() + timedelta(hours=2)  # 2-hour expiry

            # Store reset token (assuming we add these fields to User model)
            user.password_reset_token = reset_token
            user.password_reset_expires = reset_expires
            db.session.commit()

            # Prepare email context
            reset_url = f"{current_app.config.get('BASE_URL', '')}/auth/reset-password/{user.id}/{reset_token}"

            template_context = {
                'user': user,
                'full_name': user.full_name,
                'reset_url': reset_url,
                'reset_token': reset_token,
                'expires_hours': 2,
                'expires_time': reset_expires.strftime('%B %d, %Y at %I:%M %p'),
                'current_time': datetime.now(),
                'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
            }

            # Send password reset email using email service
            task_id = email_service.send_notification(
                recipient=user.email,
                template='password_reset',
                subject=f'Password Reset Request - {current_app.config.get("SITE_NAME", "Programming Course")}',
                template_context=template_context,
                priority=Priority.HIGH,
                group_id='password_reset',
                batch_id=f"password_reset_{user.id}_{int(datetime.now().timestamp())}"
            )

            logger.info(f"Password reset email queued for user: {user.username}, task_id: {task_id}")
            return True, "If the email exists, a reset link has been sent.", task_id

        except Exception as e:
            logger.error(f"Password reset initiation error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred. Please try again later.", None

    @staticmethod
    def verify_reset_token(user_id, token):
        """
        Verify password reset token validity.

        Args:
            user_id: User ID
            token: Reset token

        Returns:
            tuple: (valid: bool, user: User|None, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            user = db.session.query(User).filter_by(id=user_id, is_active=True).first()

            if not user:
                logger.warning(f"Reset token verification for non-existent user: {user_id}")
                return False, None, "Invalid reset link"

            if not user.password_reset_token or user.password_reset_token != token:
                logger.warning(f"Invalid reset token for user: {user.username}")
                return False, None, "Invalid or expired reset link"

            if not user.password_reset_expires or datetime.utcnow() > user.password_reset_expires:
                logger.warning(f"Expired reset token for user: {user.username}")
                return False, None, "Reset link has expired. Please request a new one."

            logger.info(f"Valid reset token verified for user: {user.username}")
            return True, user, "Reset token is valid"

        except Exception as e:
            logger.error(f"Reset token verification error: {str(e)}", exc_info=True)
            return False, None, "An error occurred. Please try again."

    @staticmethod
    def complete_password_reset(user_id, token, new_password):
        """
        Complete password reset with new password.

        Args:
            user_id: User ID
            token: Reset token
            new_password: New password

        Returns:
            tuple: (success: bool, message: str, task_id: str|None)
        """
        logger = logging.getLogger('auth_service')

        try:
            # Verify token first
            valid, user, message = AuthService.verify_reset_token(user_id, token)

            if not valid:
                return False, message, None

            # Validate password strength
            if len(new_password) < 8:
                return False, "Password must be at least 8 characters long", None

            # Update password
            user.set_password(new_password)

            # Clear reset token
            user.password_reset_token = None
            user.password_reset_expires = None

            # Reset failed login attempts and unlock account
            user.failed_login_attempts = 0
            user.locked_until = None

            db.session.commit()

            # Send confirmation email
            try:
                template_context = {
                    'user': user,
                    'full_name': user.full_name,
                    'reset_time': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                    'ip_address': request.remote_addr if request else 'Unknown',
                    'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
                }

                task_id = email_service.send_notification(
                    recipient=user.email,
                    template='password_reset_confirmation',
                    subject=f'Password Changed Successfully - {current_app.config.get("SITE_NAME", "Programming Course")}',
                    template_context=template_context,
                    priority=Priority.NORMAL,
                    group_id='password_reset_confirmation'
                )

                logger.info(f"Password reset completed for user: {user.username}")
                return True, "Password has been reset successfully. You can now login with your new password.", task_id

            except Exception as email_error:
                # Password was reset successfully, but email failed
                logger.warning(f"Password reset successful but confirmation email failed: {email_error}")
                return True, "Password has been reset successfully. You can now login with your new password.", None

        except Exception as e:
            logger.error(f"Password reset completion error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred while resetting password. Please try again.", None

    @staticmethod
    def change_password(user, current_password, new_password):
        """
        Change user password (requires current password verification).

        Args:
            user: User object
            current_password: Current password for verification
            new_password: New password

        Returns:
            tuple: (success: bool, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            # Verify current password
            if not user.check_password(current_password):
                logger.warning(f"Failed password change attempt for user: {user.username}")
                return False, "Current password is incorrect"

            # Validate new password strength
            if len(new_password) < 8:
                return False, "New password must be at least 8 characters long"

            if new_password == current_password:
                return False, "New password must be different from current password"

            # Update password
            user.set_password(new_password)
            db.session.commit()

            # Send confirmation email
            try:
                template_context = {
                    'user': user,
                    'full_name': user.full_name,
                    'change_time': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                    'ip_address': request.remote_addr if request else 'Unknown',
                    'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
                }

                email_service.send_notification(
                    recipient=user.email,
                    template='password_change_confirmation',
                    subject=f'Password Changed - {current_app.config.get("SITE_NAME", "Programming Course")}',
                    template_context=template_context,
                    priority=Priority.NORMAL,
                    group_id='password_change'
                )

            except Exception as email_error:
                logger.warning(f"Password change email notification failed: {email_error}")

            logger.info(f"Password changed successfully for user: {user.username}")
            return True, "Password changed successfully"

        except Exception as e:
            logger.error(f"Password change error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred while changing password. Please try again."

    @staticmethod
    def unlock_user_account(user_id, unlocked_by_user_id=None):
        """
        Unlock a locked user account (admin function).

        Args:
            user_id: User ID to unlock
            unlocked_by_user_id: Admin user ID performing unlock

        Returns:
            tuple: (success: bool, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            user = db.session.query(User).filter_by(id=user_id).first()

            if not user:
                return False, "User not found"

            if not user.is_locked():
                return True, "Account is not locked"

            # Unlock account
            user.unlock_account()
            db.session.commit()

            admin_info = ""
            if unlocked_by_user_id:
                admin_user = db.session.query(User).filter_by(id=unlocked_by_user_id).first()
                admin_info = f" by {admin_user.username}" if admin_user else ""

            logger.info(f"Account unlocked for user: {user.username}{admin_info}")

            # Send account unlock notification
            try:
                template_context = {
                    'user': user,
                    'full_name': user.full_name,
                    'unlock_time': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                    'unlocked_by_admin': bool(unlocked_by_user_id),
                    'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
                }

                email_service.send_notification(
                    recipient=user.email,
                    template='account_unlocked',
                    subject=f'Account Unlocked - {current_app.config.get("SITE_NAME", "Programming Course")}',
                    template_context=template_context,
                    priority=Priority.HIGH,
                    group_id='account_unlock'
                )

            except Exception as email_error:
                logger.warning(f"Account unlock email notification failed: {email_error}")

            return True, "Account unlocked successfully"

        except Exception as e:
            logger.error(f"Account unlock error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred while unlocking account"

    @staticmethod
    def deactivate_user_account(user_id, reason=None, deactivated_by_user_id=None):
        """
        Deactivate a user account.

        Args:
            user_id: User ID to deactivate
            reason: Reason for deactivation
            deactivated_by_user_id: Admin user ID performing deactivation

        Returns:
            tuple: (success: bool, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            user = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter_by(id=user_id)
                .first()
            )

            if not user:
                return False, "User not found"

            if not user.is_active:
                return True, "Account is already deactivated"

            # Deactivate account
            user.is_active = False

            # If user is a student, also handle participant-related deactivation
            if user.participant:
                # Reset consecutive missed sessions since account is being deactivated
                user.participant.consecutive_missed_sessions = 0

            db.session.commit()

            admin_info = ""
            if deactivated_by_user_id:
                admin_user = db.session.query(User).filter_by(id=deactivated_by_user_id).first()
                admin_info = f" by {admin_user.username}" if admin_user else ""

            logger.info(f"Account deactivated for user: {user.username}{admin_info}")

            # Send account deactivation notification
            try:
                template_context = {
                    'user': user,
                    'full_name': user.full_name,
                    'deactivation_time': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                    'reason': reason or 'Administrative action',
                    'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
                }

                email_service.send_notification(
                    recipient=user.email,
                    template='account_deactivated',
                    subject=f'Account Deactivated - {current_app.config.get("SITE_NAME", "Programming Course")}',
                    template_context=template_context,
                    priority=Priority.HIGH,
                    group_id='account_deactivation'
                )

            except Exception as email_error:
                logger.warning(f"Account deactivation email notification failed: {email_error}")

            return True, "Account deactivated successfully"

        except Exception as e:
            logger.error(f"Account deactivation error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred while deactivating account"

    @staticmethod
    def reactivate_user_account(user_id, reactivated_by_user_id=None):
        """
        Reactivate a deactivated user account.

        Args:
            user_id: User ID to reactivate
            reactivated_by_user_id: Admin user ID performing reactivation

        Returns:
            tuple: (success: bool, message: str)
        """
        logger = logging.getLogger('auth_service')

        try:
            user = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter_by(id=user_id)
                .first()
            )

            if not user:
                return False, "User not found"

            if user.is_active:
                return True, "Account is already active"

            # Reactivate account
            user.is_active = True

            # Reset security-related fields
            user.failed_login_attempts = 0
            user.locked_until = None

            # If user is a student, also handle participant reactivation
            if user.participant:
                user.participant.reactivate_user_account()

            db.session.commit()

            admin_info = ""
            if reactivated_by_user_id:
                admin_user = db.session.query(User).filter_by(id=reactivated_by_user_id).first()
                admin_info = f" by {admin_user.username}" if admin_user else ""

            logger.info(f"Account reactivated for user: {user.username}{admin_info}")

            # Send account reactivation notification
            try:
                template_context = {
                    'user': user,
                    'full_name': user.full_name,
                    'reactivation_time': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                    'login_url': f"{current_app.config.get('BASE_URL', '')}/auth/login",
                    'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com')
                }

                email_service.send_notification(
                    recipient=user.email,
                    template='account_reactivated',
                    subject=f'Account Reactivated - {current_app.config.get("SITE_NAME", "Programming Course")}',
                    template_context=template_context,
                    priority=Priority.HIGH,
                    group_id='account_reactivation'
                )

            except Exception as email_error:
                logger.warning(f"Account reactivation email notification failed: {email_error}")

            return True, "Account reactivated successfully"

        except Exception as e:
            logger.error(f"Account reactivation error: {str(e)}", exc_info=True)
            db.session.rollback()
            return False, "An error occurred while reactivating account"

    @staticmethod
    def send_welcome_email(user_id, password=None):
        """
        Send welcome email to new user (typically for new student accounts).

        Args:
            user_id: User ID
            password: Temporary password (if applicable)

        Returns:
            tuple: (success: bool, task_id: str|None)
        """
        logger = logging.getLogger('auth_service')

        try:
            user = (
                db.session.query(User)
                .options(
                    joinedload(User.participant),
                    joinedload(User.roles)
                )
                .filter_by(id=user_id)
                .first()
            )

            if not user:
                logger.error(f"Welcome email: User not found: {user_id}")
                return False, None

            # Prepare template context
            template_context = {
                'user': user,
                'full_name': user.full_name,
                'username': user.username,
                'temporary_password': password,
                'login_url': f"{current_app.config.get('BASE_URL', '')}/auth/login",
                'is_student': user.is_student(),
                'primary_role': user.primary_role,
                'contact_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com'),
                'site_name': current_app.config.get('SITE_NAME', 'Programming Course')
            }

            # Send welcome email
            task_id = email_service.send_notification(
                recipient=user.email,
                template='welcome_new_user',
                subject=f'Welcome to {current_app.config.get("SITE_NAME", "Programming Course")} - Login Details',
                template_context=template_context,
                priority=Priority.HIGH,
                group_id='welcome_email',
                batch_id=f"welcome_{user.id}_{int(datetime.now().timestamp())}"
            )

            logger.info(f"Welcome email queued for user: {user.username}, task_id: {task_id}")
            return True, task_id

        except Exception as e:
            logger.error(f"Welcome email error: {str(e)}", exc_info=True)
            return False, None

    @staticmethod
    def get_user_login_history(user_id, limit=10):
        """
        Get user login history (if tracking is implemented).

        Args:
            user_id: User ID
            limit: Number of records to return

        Returns:
            dict: Login history data
        """
        logger = logging.getLogger('auth_service')

        try:
            user = db.session.query(User).filter_by(id=user_id).first()

            if not user:
                return None

            # Return basic login information from user model
            return {
                'user_id': user.id,
                'username': user.username,
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'login_count': user.login_count,
                'failed_attempts': user.failed_login_attempts,
                'is_locked': user.is_locked(),
                'locked_until': user.locked_until.isoformat() if user.locked_until else None,
                'password_changed_at': user.password_changed_at.isoformat() if user.password_changed_at else None
            }

        except Exception as e:
            logger.error(f"Login history retrieval error: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def validate_password_strength(password):
        """
        Validate password strength.

        Args:
            password: Password to validate

        Returns:
            tuple: (valid: bool, message: str, score: int)
        """
        score = 0
        issues = []

        # Length check
        if len(password) < 8:
            issues.append("Password must be at least 8 characters long")
        else:
            score += 1

        # Character variety checks
        if any(c.islower() for c in password):
            score += 1
        else:
            issues.append("Password should contain lowercase letters")

        if any(c.isupper() for c in password):
            score += 1
        else:
            issues.append("Password should contain uppercase letters")

        if any(c.isdigit() for c in password):
            score += 1
        else:
            issues.append("Password should contain numbers")

        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            score += 1
        else:
            issues.append("Password should contain special characters")

        # Common password check (basic)
        common_passwords = ['password', '123456', 'qwerty', 'abc123', 'password123']
        if password.lower() in common_passwords:
            score = 0
            issues = ["Password is too common. Please choose a more secure password."]

        is_valid = len(issues) == 0 and score >= 3
        message = "Password is strong" if is_valid else "; ".join(issues)

        return is_valid, message, score
