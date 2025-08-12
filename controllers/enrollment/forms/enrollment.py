# enrollment/forms/enrollment.py
from flask import current_app
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import (
    StringField, EmailField, TelField, RadioField, SelectField,
    TextAreaField, DecimalField, BooleanField, HiddenField, SearchField
)
from wtforms.validators import (
    DataRequired, Email, Optional, NumberRange, Length,
    ValidationError, Regexp
)
from models.enrollment import StudentEnrollment
from models.participant import Participant
from config import Config


class BaseEnrollmentForm(FlaskForm):
    """Base form with common validation methods."""

    def validate_email_unique(self, field):
        """Check if email is already used in enrollments or participants."""
        # Skip validation if email hasn't changed (for edit forms)
        if hasattr(self, '_original_email') and field.data == self._original_email:
            return

        # Check in enrollments
        existing_enrollment = StudentEnrollment.query.filter_by(email=field.data).first()
        if existing_enrollment:
            raise ValidationError(f'Email already has application #{existing_enrollment.application_number}')

        # Check in participants
        existing_participant = Participant.query.filter_by(email=field.data).first()
        if existing_participant:
            raise ValidationError(f'Email is already enrolled as participant {existing_participant.unique_id}')

    def validate_phone_format(self, field):
        """Validate phone number format."""
        if field.data:
            # Remove common formatting characters
            cleaned = field.data.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not cleaned.replace('+', '').isdigit():
                raise ValidationError('Phone number should contain only digits, spaces, hyphens, and plus sign')


class EnrollmentForm(BaseEnrollmentForm):
    """Complete enrollment application form - matches create_enrollment route."""

    # Personal Information
    first_name = StringField('First Name', validators=[
        DataRequired(message="First name is required"),
        Length(min=2, max=80, message="First name must be between 2 and 80 characters"),
        Regexp(r'^[a-zA-Z\s\'-]+$', message="First name should contain only letters, spaces, hyphens, and apostrophes")
    ], render_kw={'placeholder': 'Enter your first name'})

    second_name = StringField('Middle Name', validators=[
        Optional(),
        Length(max=80, message="Middle name must be less than 80 characters"),
        Regexp(r'^[a-zA-Z\s\'-]*$', message="Middle name should contain only letters, spaces, hyphens, and apostrophes")
    ], render_kw={'placeholder': 'Middle name (optional)'})

    surname = StringField('Surname', validators=[
        DataRequired(message="Surname is required"),
        Length(min=2, max=80, message="Surname must be between 2 and 80 characters"),
        Regexp(r'^[a-zA-Z\s\'-]+$', message="Surname should contain only letters, spaces, hyphens, and apostrophes")
    ], render_kw={'placeholder': 'Enter your surname'})

    # Contact Information
    email = EmailField('Email Address', validators=[
        DataRequired(message="Email address is required"),
        Email(message="Please enter a valid email address"),
        Length(max=120, message="Email must be less than 120 characters"),
        BaseEnrollmentForm.validate_email_unique
    ], render_kw={'placeholder': 'your.email@example.com'})

    phone = TelField('Phone Number', validators=[
        DataRequired(message="Phone number is required"),
        Length(min=10, max=20, message="Phone number must be between 10 and 20 characters"),
        BaseEnrollmentForm.validate_phone_format
    ], render_kw={'placeholder': '+254 7XX XXX XXX'})

    # Learning Resources
    has_laptop = RadioField('Do you have a laptop?',
                            choices=[('yes', 'Yes, I have a laptop'), ('no', 'No, I don\'t have a laptop')],
                            validators=[DataRequired(message="Please select whether you have a laptop")]
                            )

    laptop_brand = StringField('Laptop Brand', validators=[
        Optional(),
        Length(max=50, message="Laptop brand must be less than 50 characters")
    ], render_kw={'placeholder': 'e.g., Dell, HP, Lenovo'})

    laptop_model = StringField('Laptop Model', validators=[
        Optional(),
        Length(max=100, message="Laptop model must be less than 100 characters")
    ], render_kw={'placeholder': 'e.g., Inspiron 15, ThinkPad E14'})

    needs_laptop_rental = BooleanField('I need laptop rental assistance')

    # Payment Information
    receipt_number = StringField('Receipt Number', validators=[
        DataRequired(message="Receipt number is required"),
        Length(min=1, max=100, message="Receipt number must be between 1 and 100 characters")
    ], render_kw={'placeholder': 'Enter receipt number'})

    payment_amount = DecimalField('Payment Amount (KES)', validators=[
        DataRequired(message="Payment amount is required"),
        NumberRange(min=0.01, message="Payment amount must be greater than 0")
    ], places=2, render_kw={'placeholder': 'Enter amount paid', 'min': '0', 'step': '0.01'})

    receipt_file = FileField('Payment Receipt', validators=[
        FileRequired(message="Payment receipt is required"),
        FileAllowed(['png', 'jpg', 'jpeg', 'pdf', 'webp'],
                    message="Only PNG, JPG, PDF, and WebP files are allowed")
    ])

    # Additional Information
    emergency_contact = StringField('Emergency Contact Name', validators=[
        Optional(),
        Length(max=100, message="Emergency contact name must be less than 100 characters")
    ], render_kw={'placeholder': 'Full name of emergency contact'})

    emergency_phone = TelField('Emergency Contact Phone', validators=[
        Optional(),
        Length(max=20, message="Emergency phone must be less than 20 characters"),
        BaseEnrollmentForm.validate_phone_format
    ], render_kw={'placeholder': '+254 7XX XXX XXX'})

    how_did_you_hear = SelectField('How did you hear about us?',
                                   choices=[
                                       ('', 'Select an option'),
                                       ('social_media', 'Social Media'),
                                       ('friend_referral', 'Friend/Family Referral'),
                                       ('online_search', 'Online Search'),
                                       ('advertisement', 'Advertisement'),
                                       ('community_board', 'Community Board'),
                                       ('other', 'Other')
                                   ],
                                   validators=[Optional()]
                                   )

    previous_attendance = RadioField('Have you attended our courses before?',
                                     choices=[('yes', 'Yes'), ('no', 'No')],
                                     validators=[Optional()],
                                     default='no'
                                     )

    special_requirements = TextAreaField('Special Requirements or Accommodations', validators=[
        Optional(),
        Length(max=1000, message="Special requirements must be less than 1000 characters")
    ], render_kw={
        'placeholder': 'Please describe any special requirements, disabilities, or accommodations you need for the course...',
        'rows': 4
    })

    def validate_receipt_file(self, field):
        """Additional validation for receipt file size."""
        if field.data:
            # Check file size (5MB limit)
            max_size = current_app.config['MAX_RECEIPT_SIZE']
            if hasattr(field.data, 'content_length') and field.data.content_length > max_size:
                raise ValidationError(f'File size must be less than {max_size // (1024 * 1024)}MB')


class EditEnrollmentForm(BaseEnrollmentForm):
    """Form for editing enrollment information - matches edit_enrollment route."""

    # Only editable fields based on EnrollmentService.can_edit_enrollment
    phone = TelField('Phone Number', validators=[
        DataRequired(message="Phone number is required"),
        Length(min=10, max=20, message="Phone number must be between 10 and 20 characters"),
        BaseEnrollmentForm.validate_phone_format
    ], render_kw={'placeholder': '+254 7XX XXX XXX'})

    # Learning Resources (conditionally editable)
    has_laptop = RadioField('Do you have a laptop?',
                            choices=[('yes', 'Yes, I have a laptop'), ('no', 'No, I don\'t have a laptop')],
                            validators=[DataRequired(message="Please select whether you have a laptop")]
                            )

    laptop_brand = StringField('Laptop Brand', validators=[
        Optional(),
        Length(max=50, message="Laptop brand must be less than 50 characters")
    ], render_kw={'placeholder': 'e.g., Dell, HP, Lenovo'})

    laptop_model = StringField('Laptop Model', validators=[
        Optional(),
        Length(max=100, message="Laptop model must be less than 100 characters")
    ], render_kw={'placeholder': 'e.g., Inspiron 15, ThinkPad E14'})

    needs_laptop_rental = BooleanField('I need laptop rental assistance')

    # Always editable additional information
    emergency_contact = StringField('Emergency Contact Name', validators=[
        Optional(),
        Length(max=100, message="Emergency contact name must be less than 100 characters")
    ], render_kw={'placeholder': 'Full name of emergency contact'})

    emergency_phone = TelField('Emergency Contact Phone', validators=[
        Optional(),
        Length(max=20, message="Emergency phone must be less than 20 characters"),
        BaseEnrollmentForm.validate_phone_format
    ], render_kw={'placeholder': '+254 7XX XXX XXX'})

    how_did_you_hear = SelectField('How did you hear about us?',
                                   choices=[
                                       ('', 'Select an option'),
                                       ('social_media', 'Social Media'),
                                       ('friend_referral', 'Friend/Family Referral'),
                                       ('online_search', 'Online Search'),
                                       ('advertisement', 'Advertisement'),
                                       ('community_board', 'Community Board'),
                                       ('other', 'Other')
                                   ],
                                   validators=[Optional()]
                                   )

    previous_attendance = RadioField('Have you attended our courses before?',
                                     choices=[('yes', 'Yes'), ('no', 'No')],
                                     validators=[Optional()]
                                     )

    special_requirements = TextAreaField('Special Requirements or Accommodations', validators=[
        Optional(),
        Length(max=1000, message="Special requirements must be less than 1000 characters")
    ], render_kw={
        'placeholder': 'Please describe any special requirements, disabilities, or accommodations you need for the course...',
        'rows': 4
    })

    def __init__(self, enrollment=None, *args, **kwargs):
        """Initialize form with enrollment data and store original email."""
        super().__init__(*args, **kwargs)
        if enrollment:
            self._original_email = enrollment.email


class ReceiptUpdateForm(FlaskForm):
    """Form for updating receipt information - matches update_receipt route."""

    receipt_number = StringField('Receipt Number', validators=[
        DataRequired(message="Receipt number is required"),
        Length(min=1, max=100, message="Receipt number must be between 1 and 100 characters")
    ], render_kw={'placeholder': 'Enter new receipt number'})

    payment_amount = DecimalField('Payment Amount (KES)', validators=[
        DataRequired(message="Payment amount is required"),
        NumberRange(min=0.01, message="Payment amount must be greater than 0")
    ], places=2, render_kw={'placeholder': 'Enter amount paid', 'min': '0', 'step': '0.01'})

    receipt_file = FileField('New Payment Receipt', validators=[
        FileRequired(message="New payment receipt is required"),
        FileAllowed(['png', 'jpg', 'jpeg', 'pdf', 'webp'],
                    message="Only PNG, JPG, PDF, and WebP files are allowed")
    ])

    def validate_receipt_file(self, field):
        """Additional validation for receipt file size."""
        if field.data:
            # Check file size (5MB limit)
            max_size = current_app.config['MAX_RECEIPT_SIZE']
            if hasattr(field.data, 'content_length') and field.data.content_length > max_size:
                raise ValidationError(f'File size must be less than {max_size // (1024 * 1024)}MB')


class SearchApplicationForm(FlaskForm):
    """Form for searching enrollment applications - matches search_application route."""

    search_term = SearchField('Email Address or Application Number', validators=[
        DataRequired(message="Please enter an email address or application number"),
        Length(min=3, max=120, message="Search term must be between 3 and 120 characters")
    ], render_kw={
        'placeholder': 'Enter your email address or application number (e.g., APP202500001)',
        'autocomplete': 'email'
    })

    def validate_search_term(self, field):
        """Validate search term format."""
        search_term = field.data.strip()

        # Check if it's an email format
        if '@' in search_term:
            try:
                Email()(None, field)  # Use email validator
            except ValidationError:
                raise ValidationError("Please enter a valid email address or application number")
        else:
            # Check if it looks like an application number
            if not (search_term.startswith('APP') and len(search_term) >= 8):
                # If it's not email and doesn't look like app number, it could still be valid
                # Just ensure it's not too short
                if len(search_term) < 3:
                    raise ValidationError("Search term is too short")


class EmailVerificationForm(FlaskForm):
    """Form for resending email verification - matches resend_verification route."""

    enrollment_id = HiddenField('Enrollment ID', validators=[
        DataRequired(message="Enrollment ID is required")
    ])


# Form field choices that can be imported elsewhere
ENROLLMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('payment_pending', 'Payment Pending'),
    ('payment_verified', 'Payment Verified'),
    ('enrolled', 'Enrolled'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled')
]

PAYMENT_STATUS_CHOICES = [
    ('unpaid', 'Unpaid'),
    ('paid', 'Paid'),
    ('verified', 'Verified')
]

HOW_DID_YOU_HEAR_CHOICES = [
    ('', 'Select an option'),
    ('social_media', 'Social Media'),
    ('friend_referral', 'Friend/Family Referral'),
    ('online_search', 'Online Search'),
    ('advertisement', 'Advertisement'),
    ('community_board', 'Community Board'),
    ('other', 'Other')
]
