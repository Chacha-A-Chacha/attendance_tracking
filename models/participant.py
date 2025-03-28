from app import db
import random
import string
from datetime import datetime


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(5), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    has_laptop = db.Column(db.Boolean, default=False)
    classroom = db.Column(db.String(10), nullable=False)  # 203 or 204
    qrcode_path = db.Column(db.String(255), nullable=True)
    registration_timestamp = db.Column(db.DateTime, default=datetime.now)
    reassignments_count = db.Column(db.Integer, default=0)

    # Relationships
    saturday_session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    sunday_session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    saturday_session = db.relationship('Session', foreign_keys=[saturday_session_id])
    sunday_session = db.relationship('Session', foreign_keys=[sunday_session_id])
    attendances = db.relationship('Attendance', back_populates='participant', lazy='dynamic')

    @staticmethod
    def generate_unique_id():
        """Generate a unique 5-digit ID"""
        while True:
            unique_id = ''.join(random.choices(string.digits, k=5))
            if not Participant.query.filter_by(unique_id=unique_id).first():
                return unique_id

    def is_correct_session(self, session_id, is_saturday=True):
        """Check if participant is in the correct session"""
        if is_saturday:
            return self.saturday_session_id == session_id
        else:
            return self.sunday_session_id == session_id

    def __repr__(self):
        return f'<Participant {self.name}>'
