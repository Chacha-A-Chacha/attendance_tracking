def verify_attendance(qr_code_data, session_id, participant_model, attendance_model):
    """
    Verifies attendance for a participant based on the scanned QR code data.

    Args:
        qr_code_data (str): The data extracted from the scanned QR code.
        session_id (int): The ID of the session for which attendance is being verified.
        participant_model (object): The model class for participant data.
        attendance_model (object): The model class for attendance records.

    Returns:
        bool: True if the attendance is successfully verified, False otherwise.
    """
    # Check if the QR code data corresponds to a valid participant
    participant = participant_model.query.filter_by(qr_code=qr_code_data).first()
    if not participant:
        return False  # Invalid QR code

    # Check if the participant has already checked in for the session
    attendance_record = attendance_model.query.filter_by(participant_id=participant.id, session_id=session_id).first()
    if attendance_record:
        return False  # Participant has already checked in

    # Create a new attendance record
    new_attendance = attendance_model(participant_id=participant.id, session_id=session_id)
    new_attendance.save()  # Assuming save() is a method to persist the record

    return True  # Attendance successfully verified


def get_attendance_report(session_id, attendance_model):
    """
    Generates an attendance report for a specific session.

    Args:
        session_id (int): The ID of the session for which the report is generated.
        attendance_model (object): The model class for attendance records.

    Returns:
        list: A list of participants who attended the session.
    """
    attendance_records = attendance_model.query.filter_by(session_id=session_id).all()
    return [record.participant for record in attendance_records]  # Assuming each record has a participant attribute