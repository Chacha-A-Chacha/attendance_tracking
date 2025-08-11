# models/enrollment.py
from . import db
from sqlalchemy import Index, func
from .base import BaseModel
import secrets


class EnrollmentStatus:
    """Enrollment status constants."""
    PENDING = 'pending'
    PAYMENT_PENDING = 'payment_pending'
    PAYMENT_VERIFIED = 'payment_verified'
    ENROLLED = 'enrolled'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'


class PaymentStatus:
    """Payment status constants."""
    UNPAID = 'unpaid'
    PAID = 'paid'
    VERIFIED = 'verified'


class StudentEnrollment(BaseModel):
    """Model for student enrollment applications before participant creation."""

    __tablename__ = 'student_enrollment'

    # Personal Information
    surname = db.Column(db.String(80), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    second_name = db.Column(db.String(80), nullable=True)  # Optional middle name

    # Contact Information
    email = db.Column(db.String(120), unique=True, nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verification_token = db.Column(db.String(255), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)
    phone = db.Column(db.String(20), nullable=False)

    # Payment Information
    payment_status = db.Column(db.String(20), default=PaymentStatus.UNPAID, nullable=False)
    is_paid = db.Column(db.Boolean, default=False, nullable=False)
    receipt_number = db.Column(db.String(100), nullable=True)
    receipt_upload_path = db.Column(db.String(255), nullable=True)
    payment_amount = db.Column(db.Numeric(10, 2), nullable=True)
    payment_date = db.Column(db.DateTime, nullable=True)
    payment_verified_at = db.Column(db.DateTime, nullable=True)
    payment_verified_by = db.Column(db.String(36), nullable=True)  # User ID who verified

    # Learning Resources
    has_laptop = db.Column(db.Boolean, default=False, nullable=False)
    laptop_brand = db.Column(db.String(50), nullable=True)
    laptop_model = db.Column(db.String(100), nullable=True)
    needs_laptop_rental = db.Column(db.Boolean, default=False, nullable=False)

    # Enrollment Processing
    enrollment_status = db.Column(db.String(20), default=EnrollmentStatus.PENDING, nullable=False)
    application_number = db.Column(db.String(20), unique=True, nullable=False)
    submitted_at = db.Column(db.DateTime, default=func.now(), nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)
    processed_by = db.Column(db.String(36), nullable=True)  # User ID who processed
    participant_created_id = db.Column(db.String(36), nullable=True)  # Reference to created participant

    # Additional Information
    emergency_contact = db.Column(db.String(100), nullable=True)
    emergency_phone = db.Column(db.String(20), nullable=True)
    special_requirements = db.Column(db.Text, nullable=True)
    how_did_you_hear = db.Column(db.String(100), nullable=True)
    previous_attendance = db.Column(db.Boolean, default=False, nullable=False)

    # Processing Notes
    admin_notes = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    # Optimized indexing strategy
    __table_args__ = (
        # Unique indexes for business constraints
        Index('uq_enrollment_email', 'email', unique=True),
        Index('uq_enrollment_application_number', 'application_number', unique=True),
        Index('uq_enrollment_receipt_number', 'receipt_number', unique=True,
              postgresql_where=db.text('receipt_number IS NOT NULL')),

        # Single column indexes for frequent filters
        Index('idx_enrollment_status', 'enrollment_status'),
        Index('idx_enrollment_payment_status', 'payment_status'),
        Index('idx_enrollment_is_paid', 'is_paid'),
        Index('idx_enrollment_email_verified', 'email_verified'),
        Index('idx_enrollment_has_laptop', 'has_laptop'),
        Index('idx_enrollment_submitted', 'submitted_at'),
        Index('idx_enrollment_processed', 'processed_at'),

        # Composite indexes for common query patterns
        Index('idx_enrollment_status_submitted', 'enrollment_status', 'submitted_at'),
        Index('idx_enrollment_payment_status_date', 'payment_status', 'payment_date'),
        Index('idx_enrollment_status_payment', 'enrollment_status', 'payment_status'),
        Index('idx_enrollment_verified_paid', 'email_verified', 'is_paid'),

        # Covering indexes for admin dashboard queries (PostgreSQL)
        Index('idx_enrollment_admin_view', 'enrollment_status', 'submitted_at',
              postgresql_include=['application_number', 'first_name', 'surname', 'email', 'payment_status']),

        # Index for payment verification workflow
        Index('idx_enrollment_payment_workflow', 'payment_status', 'payment_date',
              postgresql_include=['receipt_number', 'payment_amount']),

        # Partial indexes for active processing (PostgreSQL)
        Index('idx_enrollment_pending', 'submitted_at', 'email_verified',
              postgresql_where=db.text("enrollment_status IN ('pending', 'payment_pending')")),
        Index('idx_enrollment_ready_to_process', 'submitted_at',
              postgresql_where=db.text("enrollment_status = 'payment_verified' AND email_verified = true")),

        # Names search index for admin lookups
        Index('idx_enrollment_names', 'surname', 'first_name'),

        # Contact information index
        Index('idx_enrollment_contact', 'phone', 'email'),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.application_number:
            self.application_number = self.generate_application_number()

    @staticmethod
    def generate_application_number():
        """Generate unique application number."""
        import datetime
        year = datetime.datetime.now().year
        sequence = db.session.query(func.count(StudentEnrollment.id)).scalar() + 1
        return f"APP{year}{sequence:05d}"

    @property
    def full_name(self):
        """Get full name with optional second name."""
        if self.second_name:
            return f"{self.first_name} {self.second_name} {self.surname}"
        return f"{self.first_name} {self.surname}"

    @property
    def display_name(self):
        """Get display name (First Last)."""
        return f"{self.first_name} {self.surname}"

    def generate_email_verification_token(self):
        """Generate email verification token."""
        self.email_verification_token = secrets.token_urlsafe(32)
        self.email_verification_sent_at = func.now()
        return self.email_verification_token

    def verify_email(self, token):
        """Verify email with token."""
        if self.email_verification_token == token:
            self.email_verified = True
            self.email_verification_token = None
            return True
        return False

    def mark_payment_received(self, receipt_number, amount, verified_by_user_id=None):
        """Mark payment as received."""
        self.is_paid = True
        self.payment_status = PaymentStatus.PAID
        self.receipt_number = receipt_number
        self.payment_amount = amount
        self.payment_date = func.now()

        if verified_by_user_id:
            self.payment_verified_by = verified_by_user_id
            self.payment_verified_at = func.now()
            self.payment_status = PaymentStatus.VERIFIED

        # Update enrollment status
        if self.enrollment_status == EnrollmentStatus.PAYMENT_PENDING:
            if self.email_verified:
                self.enrollment_status = EnrollmentStatus.PAYMENT_VERIFIED

    def verify_payment(self, verified_by_user_id):
        """Verify payment by admin."""
        if self.is_paid:
            self.payment_status = PaymentStatus.VERIFIED
            self.payment_verified_by = verified_by_user_id
            self.payment_verified_at = func.now()

            # Update enrollment status if email is also verified
            if self.email_verified and self.enrollment_status != EnrollmentStatus.ENROLLED:
                self.enrollment_status = EnrollmentStatus.PAYMENT_VERIFIED

    def is_ready_for_enrollment(self):
        """Check if enrollment is ready to be processed into participant."""
        return (
                self.email_verified and
                self.payment_status == PaymentStatus.VERIFIED and
                self.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
        )

    def enroll_as_participant(self, classroom, processed_by_user_id=None):
        """Convert enrollment to participant record."""
        if not self.is_ready_for_enrollment():
            raise ValueError("Enrollment not ready for processing")

        from .participant import Participant

        # Create participant record
        participant = Participant(
            unique_id=Participant.generate_unique_id(),
            email=self.email,
            name=self.full_name,
            phone=self.phone,
            has_laptop=self.has_laptop,
            classroom=classroom
        )

        db.session.add(participant)
        db.session.flush()  # Get the participant ID

        # Update enrollment record
        self.enrollment_status = EnrollmentStatus.ENROLLED
        self.processed_at = func.now()
        self.processed_by = processed_by_user_id
        self.participant_created_id = participant.id

        return participant

    def reject_enrollment(self, reason, rejected_by_user_id=None):
        """Reject the enrollment application."""
        self.enrollment_status = EnrollmentStatus.REJECTED
        self.rejection_reason = reason
        self.processed_at = func.now()
        self.processed_by = rejected_by_user_id

    def cancel_enrollment(self):
        """Cancel the enrollment application."""
        self.enrollment_status = EnrollmentStatus.CANCELLED
        self.processed_at = func.now()

    def get_enrollment_progress(self):
        """Get enrollment progress as percentage."""
        steps_completed = 0
        total_steps = 3

        # Step 1: Basic info submitted
        steps_completed += 1

        # Step 2: Email verified
        if self.email_verified:
            steps_completed += 1

        # Step 3: Payment verified
        if self.payment_status == PaymentStatus.VERIFIED:
            steps_completed += 1

        return (steps_completed / total_steps) * 100

    def to_dict(self, include_relationships=False):
        """Override to include computed fields and exclude sensitive data."""
        result = super().to_dict(include_relationships=include_relationships)

        # Remove sensitive fields
        result.pop('email_verification_token', None)

        # Add computed fields
        result['full_name'] = self.full_name
        result['display_name'] = self.display_name
        result['is_ready_for_enrollment'] = self.is_ready_for_enrollment()
        result['enrollment_progress'] = self.get_enrollment_progress()

        return result

    def __repr__(self):
        return f'<StudentEnrollment {self.application_number} - {self.display_name}>'
