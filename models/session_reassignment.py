# models/session_reassignment.py
from app import db
from datetime import datetime


class ReassignmentStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class SessionReassignmentRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    current_session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    requested_session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    day_type = db.Column(db.String(10), nullable=False)  # 'Saturday' or 'Sunday'
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), default=ReassignmentStatus.PENDING)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    # reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Assuming an admin User model
    # exists

    # Relationships
    participant = db.relationship('Participant', backref='reassignment_requests')
    current_session = db.relationship('Session', foreign_keys=[current_session_id])
    requested_session = db.relationship('Session', foreign_keys=[requested_session_id])
    # reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_requests')

    def __repr__(self):
        return f'<SessionReassignmentRequest {self.id} - {self.status}>'
