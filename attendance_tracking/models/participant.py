from app import db
import random
import string

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(5), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    has_laptop = db.Column(db.Boolean, default=False)
    saturday_session = db.Column(db.String(50), nullable=False)
    sunday_session = db.Column(db.String(50), nullable=False)
    classroom = db.Column(db.String(10), nullable=False)  # 203 or 204
    
    @staticmethod
    def generate_unique_id():
        """Generate a unique 5-digit ID"""
        while True:
            unique_id = ''.join(random.choices(string.digits, k=5))
            if not Participant.query.filter_by(unique_id=unique_id).first():
                return unique_id
            