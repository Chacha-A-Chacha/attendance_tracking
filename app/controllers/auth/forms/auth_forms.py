# forms/auth_forms.py
"""
Flask-WTF forms for authentication functionality.
Includes login, password reset, password change, and admin user management forms.
"""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectField, TextAreaField, HiddenField
from wtforms.validators import (
    DataRequired, Email, Length, EqualTo, ValidationError, Optional, Regexp
)
from wtforms.widgets import PasswordInput
from sqlalchemy import and_, or_

from app.models.user import User, RoleType
from app.extensions import db


class LoginForm(FlaskForm):
    """User login form with username/email and password."""

    identifier = StringField(
        'Username or Email',
        validators=[
            DataRequired(message='Username or email is required'),
            Length(min=3, max=120, message='Must be between 3 and 120 characters')
        ],
        render_kw={
            'placeholder': 'Enter your username or email',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'username',
            'autofocus': True
        }
    )

    password = PasswordField(
        'Password',
        validators=[
            DataRequired(message='Password is required'),
            Length(min=1, max=255, message='Password is too long')
        ],
        render_kw={
            'placeholder': 'Enter your password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'current-password'
        }
    )

    remember_me = BooleanField(
        'Remember me',
        default=False,
        render_kw={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }
    )

    next_url = HiddenField()

    def validate_identifier(self, field):
        """Validate that identifier is not empty after stripping."""
        if not field.data or not field.data.strip():
            raise ValidationError('Username or email cannot be empty')


class PasswordResetRequestForm(FlaskForm):
    """Form to request password reset by email or username."""

    email_or_username = StringField(
        'Email or Username',
        validators=[
            DataRequired(message='Email or username is required'),
            Length(min=3, max=120, message='Must be between 3 and 120 characters')
        ],
        render_kw={
            'placeholder': 'Enter your email address or username',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'username',
            'autofocus': True
        }
    )

    def validate_email_or_username(self, field):
        """Basic validation - don't reveal if user exists."""
        if not field.data or not field.data.strip():
            raise ValidationError('Email or username cannot be empty')

        # Additional client-side validation for email format if it looks like an email
        data = field.data.strip()
        if '@' in data:
            # Basic email format check
            if not data.count('@') == 1 or not '.' in data.split('@')[1]:
                raise ValidationError('Please enter a valid email address')


class PasswordResetForm(FlaskForm):
    """Form to reset password with token validation."""

    user_id = HiddenField(
        validators=[DataRequired()]
    )

    token = HiddenField(
        validators=[DataRequired()]
    )

    password = PasswordField(
        'New Password',
        validators=[
            DataRequired(message='Password is required'),
            Length(min=8, max=255, message='Password must be at least 8 characters long'),
            Regexp(
                r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)',
                message='Password must contain at least one lowercase letter, one uppercase letter, and one number'
            )
        ],
        render_kw={
            'placeholder': 'Enter your new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    password_confirm = PasswordField(
        'Confirm New Password',
        validators=[
            DataRequired(message='Password confirmation is required'),
            EqualTo('password', message='Passwords must match')
        ],
        render_kw={
            'placeholder': 'Confirm your new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    def validate_password(self, field):
        """Enhanced password validation."""
        password = field.data

        if not password:
            return

        # Check for common weak passwords
        weak_passwords = [
            'password', '123456', 'qwerty', 'abc123', 'password123',
            'admin', 'letmein', 'welcome', '123456789', 'password1'
        ]

        if password.lower() in weak_passwords:
            raise ValidationError('This password is too common. Please choose a more secure password.')

        # Check for sequential characters
        if any(password.lower().find(seq) != -1 for seq in ['123', 'abc', 'qwe']):
            raise ValidationError('Avoid using sequential characters in your password.')


class PasswordChangeForm(FlaskForm):
    """Form for users to change their password (requires current password)."""

    current_password = PasswordField(
        'Current Password',
        validators=[
            DataRequired(message='Current password is required'),
            Length(min=1, max=255, message='Password is too long')
        ],
        render_kw={
            'placeholder': 'Enter your current password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'current-password'
        }
    )

    new_password = PasswordField(
        'New Password',
        validators=[
            DataRequired(message='New password is required'),
            Length(min=8, max=255, message='Password must be at least 8 characters long'),
            Regexp(
                r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)',
                message='Password must contain at least one lowercase letter, one uppercase letter, and one number'
            )
        ],
        render_kw={
            'placeholder': 'Enter your new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    new_password_confirm = PasswordField(
        'Confirm New Password',
        validators=[
            DataRequired(message='Password confirmation is required'),
            EqualTo('new_password', message='Passwords must match')
        ],
        render_kw={
            'placeholder': 'Confirm your new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    def validate_new_password(self, field):
        """Enhanced password validation and ensure it's different from current."""
        password = field.data

        if not password:
            return

        # Check for common weak passwords
        weak_passwords = [
            'password', '123456', 'qwerty', 'abc123', 'password123',
            'admin', 'letmein', 'welcome', '123456789', 'password1'
        ]

        if password.lower() in weak_passwords:
            raise ValidationError('This password is too common. Please choose a more secure password.')

        # Check if new password is same as current password
        if hasattr(self, 'current_password') and self.current_password.data == password:
            raise ValidationError('New password must be different from your current password.')


class AdminUserCreateForm(FlaskForm):
    """Admin form to create new staff users."""

    username = StringField(
        'Username',
        validators=[
            DataRequired(message='Username is required'),
            Length(min=3, max=80, message='Username must be between 3 and 80 characters'),
            Regexp(
                r'^[a-zA-Z0-9_]+$',
                message='Username can only contain letters, numbers, and underscores'
            )
        ],
        render_kw={
            'placeholder': 'Enter username',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'username'
        }
    )

    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email is required'),
            Email(message='Please enter a valid email address'),
            Length(max=120, message='Email is too long')
        ],
        render_kw={
            'placeholder': 'Enter email address',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'email'
        }
    )

    first_name = StringField(
        'First Name',
        validators=[
            DataRequired(message='First name is required'),
            Length(min=1, max=80, message='First name must be between 1 and 80 characters'),
            Regexp(
                r'^[a-zA-Z\s\'-]+$',
                message='First name can only contain letters, spaces, hyphens, and apostrophes'
            )
        ],
        render_kw={
            'placeholder': 'Enter first name',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'given-name'
        }
    )

    last_name = StringField(
        'Last Name',
        validators=[
            DataRequired(message='Last name is required'),
            Length(min=1, max=80, message='Last name must be between 1 and 80 characters'),
            Regexp(
                r'^[a-zA-Z\s\'-]+$',
                message='Last name can only contain letters, spaces, hyphens, and apostrophes'
            )
        ],
        render_kw={
            'placeholder': 'Enter last name',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'family-name'
        }
    )

    role = SelectField(
        'Role',
        validators=[
            DataRequired(message='Role is required')
        ],
        choices=[
            (RoleType.TEACHER, 'Teacher'),
            (RoleType.CHAPLAIN, 'Chaplain'),
            (RoleType.ADMIN, 'Administrator')
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500'
        }
    )

    password = PasswordField(
        'Password',
        validators=[
            DataRequired(message='Password is required'),
            Length(min=8, max=255, message='Password must be at least 8 characters long'),
            Regexp(
                r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)',
                message='Password must contain at least one lowercase letter, one uppercase letter, and one number'
            )
        ],
        render_kw={
            'placeholder': 'Enter password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    password_confirm = PasswordField(
        'Confirm Password',
        validators=[
            DataRequired(message='Password confirmation is required'),
            EqualTo('password', message='Passwords must match')
        ],
        render_kw={
            'placeholder': 'Confirm password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    def validate_username(self, field):
        """Check if username is already taken."""
        if field.data:
            existing_user = db.session.query(User).filter_by(username=field.data.strip()).first()
            if existing_user:
                raise ValidationError('This username is already taken. Please choose a different one.')

    def validate_email(self, field):
        """Check if email is already taken."""
        if field.data:
            existing_user = db.session.query(User).filter_by(email=field.data.strip().lower()).first()
            if existing_user:
                raise ValidationError('This email address is already registered. Please use a different email.')


class AdminUserEditForm(FlaskForm):
    """Admin form to edit existing users."""

    user_id = HiddenField(
        validators=[DataRequired()]
    )

    username = StringField(
        'Username',
        validators=[
            DataRequired(message='Username is required'),
            Length(min=3, max=80, message='Username must be between 3 and 80 characters'),
            Regexp(
                r'^[a-zA-Z0-9_]+$',
                message='Username can only contain letters, numbers, and underscores'
            )
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'username'
        }
    )

    email = StringField(
        'Email',
        validators=[
            DataRequired(message='Email is required'),
            Email(message='Please enter a valid email address'),
            Length(max=120, message='Email is too long')
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'email'
        }
    )

    first_name = StringField(
        'First Name',
        validators=[
            DataRequired(message='First name is required'),
            Length(min=1, max=80, message='First name must be between 1 and 80 characters'),
            Regexp(
                r'^[a-zA-Z\s\'-]+$',
                message='First name can only contain letters, spaces, hyphens, and apostrophes'
            )
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'given-name'
        }
    )

    last_name = StringField(
        'Last Name',
        validators=[
            DataRequired(message='Last name is required'),
            Length(min=1, max=80, message='Last name must be between 1 and 80 characters'),
            Regexp(
                r'^[a-zA-Z\s\'-]+$',
                message='Last name can only contain letters, spaces, hyphens, and apostrophes'
            )
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'family-name'
        }
    )

    is_active = BooleanField(
        'Account Active',
        default=True,
        render_kw={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }
    )

    def validate_username(self, field):
        """Check if username is already taken by another user."""
        if field.data and self.user_id.data:
            existing_user = (
                db.session.query(User)
                .filter(
                    and_(
                        User.username == field.data.strip(),
                        User.id != self.user_id.data
                    )
                )
                .first()
            )
            if existing_user:
                raise ValidationError('This username is already taken. Please choose a different one.')

    def validate_email(self, field):
        """Check if email is already taken by another user."""
        if field.data and self.user_id.data:
            existing_user = (
                db.session.query(User)
                .filter(
                    and_(
                        User.email == field.data.strip().lower(),
                        User.id != self.user_id.data
                    )
                )
                .first()
            )
            if existing_user:
                raise ValidationError('This email address is already registered. Please use a different email.')


class AdminPasswordResetForm(FlaskForm):
    """Admin form to reset any user's password."""

    user_id = HiddenField(
        validators=[DataRequired()]
    )

    new_password = PasswordField(
        'New Password',
        validators=[
            DataRequired(message='New password is required'),
            Length(min=8, max=255, message='Password must be at least 8 characters long'),
            Regexp(
                r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)',
                message='Password must contain at least one lowercase letter, one uppercase letter, and one number'
            )
        ],
        render_kw={
            'placeholder': 'Enter new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    new_password_confirm = PasswordField(
        'Confirm New Password',
        validators=[
            DataRequired(message='Password confirmation is required'),
            EqualTo('new_password', message='Passwords must match')
        ],
        render_kw={
            'placeholder': 'Confirm new password',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'autocomplete': 'new-password'
        }
    )

    notify_user = BooleanField(
        'Send email notification to user',
        default=True,
        render_kw={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }
    )

    reason = TextAreaField(
        'Reason (Optional)',
        validators=[
            Optional(),
            Length(max=500, message='Reason must be less than 500 characters')
        ],
        render_kw={
            'placeholder': 'Reason for password reset (optional)',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'rows': 3
        }
    )


class AccountLockForm(FlaskForm):
    """Admin form to lock/unlock user accounts."""

    user_id = HiddenField(
        validators=[DataRequired()]
    )

    action = HiddenField(
        validators=[DataRequired()]
    )

    reason = TextAreaField(
        'Reason',
        validators=[
            DataRequired(message='Reason is required'),
            Length(min=10, max=500, message='Reason must be between 10 and 500 characters')
        ],
        render_kw={
            'placeholder': 'Please provide a reason for this action',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'rows': 4
        }
    )

    notify_user = BooleanField(
        'Send email notification to user',
        default=True,
        render_kw={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }
    )


class RoleAssignmentForm(FlaskForm):
    """Admin form to assign/remove roles from users."""

    user_id = HiddenField(
        validators=[DataRequired()]
    )

    role = SelectField(
        'Role',
        validators=[
            DataRequired(message='Role is required')
        ],
        choices=[
            (RoleType.TEACHER, 'Teacher'),
            (RoleType.CHAPLAIN, 'Chaplain'),
            (RoleType.STUDENT_REPRESENTATIVE, 'Student Representative'),
            (RoleType.ADMIN, 'Administrator')
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500'
        }
    )

    action = SelectField(
        'Action',
        validators=[
            DataRequired(message='Action is required')
        ],
        choices=[
            ('add', 'Add Role'),
            ('remove', 'Remove Role')
        ],
        render_kw={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500'
        }
    )

    reason = TextAreaField(
        'Reason (Optional)',
        validators=[
            Optional(),
            Length(max=500, message='Reason must be less than 500 characters')
        ],
        render_kw={
            'placeholder': 'Reason for role change (optional)',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500',
            'rows': 3
        }
    )