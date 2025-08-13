# models/participant.py
from ..extensions import db
import random
import string
from sqlalchemy import Index
from .base import BaseModel


class Participant(BaseModel):
    __tablename__ = 'participant'

    unique_id = db.Column(db.String(5), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

    # Personal Information
    surname = db.Column(db.String(80), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    second_name = db.Column(db.String(80), nullable=True)

    phone = db.Column(db.String(20), nullable=False)
    has_laptop = db.Column(db.Boolean, default=False)
    classroom = db.Column(db.String(10), nullable=False)  # 203 or 204
    qrcode_path = db.Column(db.String(255), nullable=True)
    registration_timestamp = db.Column(db.DateTime, default=db.func.now())
    reassignments_count = db.Column(db.Integer, default=0)

    # Graduation tracking
    graduation_status = db.Column(db.String(20), default='not_eligible',
                                  nullable=False)  # not_eligible, eligible, graduated, failed
    graduation_score = db.Column(db.Numeric(5, 2), nullable=True)  # e.g., 85.50
    graduation_fee_paid = db.Column(db.Boolean, default=False, nullable=False)
    graduation_fee_receipt_number = db.Column(db.String(100), nullable=True)
    graduation_fee_receipt_upload_path = db.Column(db.String(255), nullable=True)
    graduation_date = db.Column(db.DateTime, nullable=True)
    graduation_verified_by = db.Column(db.String(36), nullable=True)  # Admin who verified graduation
    graduation_verified_at = db.Column(db.DateTime, nullable=True)
    consecutive_missed_sessions = db.Column(db.Integer, default=0, nullable=False)

    # Foreign keys with proper indexing
    saturday_session_id = db.Column(db.String(36), db.ForeignKey('session.id'), index=True)
    sunday_session_id = db.Column(db.String(36), db.ForeignKey('session.id'), index=True)

    # Relationships
    saturday_session = db.relationship('Session', foreign_keys=[saturday_session_id])
    sunday_session = db.relationship('Session', foreign_keys=[sunday_session_id])
    attendances = db.relationship('Attendance', back_populates='participant', lazy='dynamic')
    reassignment_requests = db.relationship('SessionReassignmentRequest', back_populates='participant')

    # User relationship (one-to-one)
    user = db.relationship('User', back_populates='participant', uselist=False)

    # Optimized indexing strategy
    __table_args__ = (
        # Unique indexes for business constraints
        Index('uq_participant_unique_id', 'unique_id', unique=True),
        Index('uq_participant_email', 'email', unique=True),

        # Single column indexes for frequent filters
        Index('idx_participant_classroom', 'classroom'),
        Index('idx_participant_has_laptop', 'has_laptop'),
        Index('idx_participant_registration', 'registration_timestamp'),
        Index('idx_participant_graduation_status', 'graduation_status'),
        Index('idx_participant_graduation_fee_paid', 'graduation_fee_paid'),
        Index('idx_participant_graduation_date', 'graduation_date'),
        Index('idx_participant_consecutive_missed', 'consecutive_missed_sessions'),

        # Composite indexes for common query patterns
        Index('idx_participant_classroom_laptop', 'classroom', 'has_laptop'),
        Index('idx_participant_classroom_created', 'classroom', 'created_at'),
        Index('idx_participant_graduation_status_score', 'graduation_status', 'graduation_score'),
        Index('idx_participant_graduation_fee_status', 'graduation_fee_paid', 'graduation_status'),

        # Covering index for common participant lookups
        # PostgreSQL only - includes name in index to avoid table lookup
        Index('idx_participant_lookup', 'unique_id', postgresql_include=['first_name', 'surname', 'email']),
    )

    @staticmethod
    def generate_unique_id():
        """Generate a unique 5-digit ID"""
        while True:
            unique_id = ''.join(random.choices(string.digits, k=5))
            if not Participant.query.filter_by(unique_id=unique_id).first():
                return unique_id

    @property
    def full_name(self):
        """Get full name with optional second name."""
        if self.second_name:
            return f"{self.first_name} {self.second_name} {self.surname}"
        return f"{self.first_name} {self.surname}"

    def is_correct_session(self, session_id, is_saturday=True):
        """Check if participant is in the correct session"""
        if is_saturday:
            return self.saturday_session_id == session_id
        else:
            return self.sunday_session_id == session_id

    def create_user_account(self, username=None, password=None, roles=None):
        """Create a user account for this participant."""
        from .user import User, RoleType
        import secrets

        if self.user:
            return self.user  # User already exists

        # Generate username if not provided
        if not username:
            username = self.unique_id

        # Create user
        user = User(
            username=username,
            email=self.email,
            first_name=self.first_name,
            last_name=self.surname or self.second_name,
            participant_id=self.id
        )

        if password:
            user.set_password(password)
        else:
            # Generate temporary password
            temp_password = secrets.token_urlsafe(8)
            user.set_password(temp_password)
            password = temp_password

        # Assign roles
        if not roles:
            roles = [RoleType.STUDENT]

        for role_name in roles:
            user.add_role(role_name)

        db.session.add(user)
        return user, password

    def has_user_account(self):
        """Check if participant has an associated user account."""
        return self.user is not None

    def get_attendance_summary(self):
        """Get attendance summary for this participant."""
        total_attendances = self.attendances.count()
        correct_attendances = self.attendances.filter_by(is_correct_session=True).count()
        incorrect_attendances = self.attendances.filter_by(is_correct_session=False).count()

        return {
            'total': total_attendances,
            'correct': correct_attendances,
            'incorrect': incorrect_attendances,
            'accuracy_rate': (correct_attendances / total_attendances * 100) if total_attendances > 0 else 0
        }

    def get_recent_attendances(self, limit=10):
        """Get recent attendance records."""
        return self.attendances.order_by(db.desc('timestamp')).limit(limit).all()

    def mark_graduation_fee_paid(self, receipt_number, verified_by_user_id=None):
        """Mark graduation fee as paid."""
        self.graduation_fee_paid = True
        self.graduation_fee_receipt_number = receipt_number

        if verified_by_user_id:
            self.graduation_verified_by = verified_by_user_id
            self.graduation_verified_at = db.func.now()

    def record_graduation(self, score, verified_by_user_id):
        """Record successful graduation."""
        self.graduation_score = score
        self.graduation_status = 'graduated'
        self.graduation_date = db.func.now()
        self.graduation_verified_by = verified_by_user_id
        self.graduation_verified_at = db.func.now()

        # Deactivate user account upon graduation
        if self.user:
            self.user.is_active = False

    def is_eligible_for_graduation(self):
        """Check if participant meets graduation requirements."""
        # Can be customized based on attendance rate, assignments, etc.
        return (
                self.graduation_status in ['eligible', 'graduated'] and
                self.graduation_fee_paid
        )

    def record_attendance(self, session_id, is_present=True):
        """Record attendance and handle consecutive absences."""
        if is_present:
            # Reset consecutive missed sessions on attendance
            self.consecutive_missed_sessions = 0
        else:
            # Increment consecutive missed sessions
            self.consecutive_missed_sessions += 1

            # Deactivate user account after 3 consecutive misses
            if self.consecutive_missed_sessions >= 3 and self.user:
                self.user.is_active = False

    def reactivate_user_account(self):
        """Reactivate user account and reset consecutive missed sessions."""
        if self.user:
            self.user.is_active = True
        self.consecutive_missed_sessions = 0

    def to_dict(self, include_relationships=False):
        """Override to include computed fields."""
        result = super().to_dict(include_relationships=include_relationships)

        # Add computed fields
        result['has_user_account'] = self.has_user_account()
        result['attendance_summary'] = self.get_attendance_summary()
        result['full_name'] = self.full_name

        if include_relationships and self.user:
            result['user'] = self.user.to_dict()

        return result

    def __repr__(self):
        return f'<Participant {self.full_name} ({self.unique_id})>'
