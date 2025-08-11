from app import db


class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time_slot = db.Column(db.String(50), nullable=False)
    day = db.Column(db.String(10), nullable=False)  # 'Saturday' or 'Sunday'

    # Participants with this session (using back_populates)
    saturday_participants = db.relationship('Participant',
                                            foreign_keys='Participant.saturday_session_id',
                                            back_populates='saturday_session')
    sunday_participants = db.relationship('Participant',
                                          foreign_keys='Participant.sunday_session_id',
                                          back_populates='sunday_session')

    # Attendances for this session
    attendances = db.relationship('Attendance', back_populates='session', lazy='dynamic')

    def __repr__(self):
        return f'<Session {self.day} {self.time_slot}>'
