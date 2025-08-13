# models/session.py
from app.extensions import db
from sqlalchemy import Index
from .base import BaseModel


class Session(BaseModel):
    __tablename__ = 'session'

    time_slot = db.Column(db.String(50), nullable=False)
    day = db.Column(db.String(10), nullable=False)  # 'Saturday' or 'Sunday'
    max_capacity = db.Column(db.Integer, default=30)  # Added for capacity management
    is_active = db.Column(db.Boolean, default=True)  # Added for session management

    # Participants with this session (using back_populates)
    saturday_participants = db.relationship('Participant',
                                            foreign_keys='Participant.saturday_session_id',
                                            back_populates='saturday_session')
    sunday_participants = db.relationship('Participant',
                                          foreign_keys='Participant.sunday_session_id',
                                          back_populates='sunday_session')

    # Attendances for this session
    attendances = db.relationship('Attendance', back_populates='session', lazy='dynamic')

    # Optimized indexing strategy
    __table_args__ = (
        # Composite index for the most common query pattern
        Index('idx_session_day_time', 'day', 'time_slot'),
        Index('idx_session_day_active', 'day', 'is_active'),

        # Single column indexes
        Index('idx_session_day', 'day'),
        Index('idx_session_active', 'is_active'),

        # Covering index for session listings (PostgreSQL)
        Index('idx_session_listing', 'day', 'is_active',
              postgresql_include=['time_slot', 'max_capacity']),

        # Unique constraint for business logic
        Index('uq_session_day_time', 'day', 'time_slot', unique=True),
    )

    @property
    def current_capacity_saturday(self):
        """Get current number of Saturday participants"""
        return len(self.saturday_participants)

    @property
    def current_capacity_sunday(self):
        """Get current number of Sunday participants"""
        return len(self.sunday_participants)

    def is_full(self, day_type='Saturday'):
        """Check if session is at capacity"""
        current = self.current_capacity_saturday if day_type == 'Saturday' else self.current_capacity_sunday
        return current >= self.max_capacity

    def __repr__(self):
        return f'<Session {self.day} {self.time_slot}>'
