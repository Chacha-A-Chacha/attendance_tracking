# models/session_reassignment.py
from app.extensions import db
from sqlalchemy import Index
from .base import BaseModel


class ReassignmentStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class SessionReassignmentRequest(BaseModel):
    __tablename__ = 'session_reassignment_request'

    participant_id = db.Column(db.String(36), db.ForeignKey('participant.id'), nullable=False, index=True)
    current_session_id = db.Column(db.String(36), db.ForeignKey('session.id'), nullable=False, index=True)
    requested_session_id = db.Column(db.String(36), db.ForeignKey('session.id'), nullable=False, index=True)
    day_type = db.Column(db.String(10), nullable=False, index=True)  # 'Saturday' or 'Sunday'
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), default=ReassignmentStatus.PENDING, index=True)
    admin_notes = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(10), default='normal')  # Added: low, normal, high
    # reviewed_by = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=True)

    # Relationships
    participant = db.relationship('Participant', back_populates='reassignment_requests')
    current_session = db.relationship('Session', foreign_keys=[current_session_id])
    requested_session = db.relationship('Session', foreign_keys=[requested_session_id])
    # reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_requests')

    # Optimized indexing strategy
    __table_args__ = (
        # Composite indexes for common admin queries
        Index('idx_reassignment_status_created', 'status', 'created_at'),
        Index('idx_reassignment_status_day', 'status', 'day_type'),
        Index('idx_reassignment_participant_status', 'participant_id', 'status'),
        Index('idx_reassignment_day_priority', 'day_type', 'priority', 'created_at'),

        # Covering index for admin dashboard (PostgreSQL)
        Index('idx_reassignment_admin_view', 'status', 'created_at',
              postgresql_include=['participant_id', 'day_type', 'priority']),

        # Partial indexes for active requests (PostgreSQL only)
        Index('idx_reassignment_pending', 'created_at', 'day_type',
              postgresql_where=db.text("status = 'pending'")),
        Index('idx_reassignment_participant_pending', 'participant_id',
              postgresql_where=db.text("status = 'pending'")),

        # Index for session-based queries
        Index('idx_reassignment_sessions', 'current_session_id', 'requested_session_id'),

        # Business constraint: prevent duplicate pending requests
        Index('uq_reassignment_participant_day_pending', 'participant_id', 'day_type',
              postgresql_where=db.text("status = 'pending'"), unique=True),
    )

    def approve(self, admin_notes=None):
        """Approve the reassignment request"""
        self.status = ReassignmentStatus.APPROVED
        self.reviewed_at = db.func.now()
        if admin_notes:
            self.admin_notes = admin_notes
        return self

    def reject(self, admin_notes=None):
        """Reject the reassignment request"""
        self.status = ReassignmentStatus.REJECTED
        self.reviewed_at = db.func.now()
        if admin_notes:
            self.admin_notes = admin_notes
        return self

    @property
    def is_pending(self):
        return self.status == ReassignmentStatus.PENDING

    @property
    def is_approved(self):
        return self.status == ReassignmentStatus.APPROVED

    @property
    def is_rejected(self):
        return self.status == ReassignmentStatus.REJECTED

    def __repr__(self):
        return f'<SessionReassignmentRequest {self.id} - {self.status}>'
