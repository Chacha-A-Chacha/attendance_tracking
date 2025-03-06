from app import db
from datetime import datetime


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    is_correct_session = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='absent') 
    
    # Relationships
    participant = db.relationship('Participant', back_populates='attendances')
    session = db.relationship('Session', back_populates='attendances')
    
    def __repr__(self):
        status = "Correct" if self.is_correct_session else "Incorrect"
        return f'<Attendance {self.participant.name} - {status}>'
