class Attendance:
    def __init__(self, participant_id, session_id, check_in_time, check_out_time=None):
        self.participant_id = participant_id
        self.session_id = session_id
        self.check_in_time = check_in_time
        self.check_out_time = check_out_time

    def check_out(self, check_out_time):
        self.check_out_time = check_out_time

    def __repr__(self):
        return f"<Attendance(participant_id={self.participant_id}, session_id={self.session_id}, check_in_time={self.check_in_time}, check_out_time={self.check_out_time})>"