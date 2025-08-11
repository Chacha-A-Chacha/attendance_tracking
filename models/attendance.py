# models/attendance.py
from app import db
from sqlalchemy import Index
from .base import BaseModel


class Attendance(BaseModel):
    __tablename__ = 'attendance'

    participant_id = db.Column(db.String(36), db.ForeignKey('participant.id'), nullable=False, index=True)
    session_id = db.Column(db.String(36), db.ForeignKey('session.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    is_correct_session = db.Column(db.Boolean, default=False, index=True)
    status = db.Column(db.String(20), default='absent', index=True)
    check_in_method = db.Column(db.String(20), default='qr_code')  # Added: qr_code, manual, etc.

    # Relationships
    participant = db.relationship('Participant', back_populates='attendances')
    session = db.relationship('Session', back_populates='attendances')

    # Optimized indexing strategy
    __table_args__ = (
        # Composite indexes for common query patterns
        Index('idx_attendance_participant_session', 'participant_id', 'session_id'),
        Index('idx_attendance_session_date', 'session_id', 'timestamp'),
        Index('idx_attendance_participant_date', 'participant_id', 'timestamp'),
        Index('idx_attendance_status_correct', 'status', 'is_correct_session'),
        Index('idx_attendance_session_status', 'session_id', 'status'),

        # Covering index for attendance reports (PostgreSQL)
        Index('idx_attendance_report', 'session_id', 'timestamp',
              postgresql_include=['participant_id', 'status', 'is_correct_session']),

        # Index for date-based queries (common for reports)
        Index('idx_attendance_date_status', 'timestamp', 'status'),

        # Partial index for incorrect sessions (PostgreSQL only)
        Index('idx_attendance_incorrect', 'participant_id', 'timestamp',
              postgresql_where=db.text('is_correct_session = false')),

        # Unique constraint to prevent duplicate check-ins
        Index('uq_attendance_participant_session_date', 'participant_id', 'session_id',
              db.func.date('timestamp'), unique=True),
    )

    def __repr__(self):
        status = "Correct" if self.is_correct_session else "Incorrect"
        return f'<Attendance {self.participant.name if self.participant else "Unknown"} - {status}>'
