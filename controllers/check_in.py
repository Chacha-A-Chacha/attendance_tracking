# controllers/check_in.py
from flask import Blueprint, render_template, request, jsonify, current_app
from services.verification import AttendanceVerifier

check_in_bp = Blueprint('check_in', __name__)


@check_in_bp.route('/')
def scanner():
    """Display QR code scanner interface"""
    # Get all available sessions for the dropdown
    return render_template('check_in/scanner.html')


@check_in_bp.route('/verify', methods=['POST'])
def verify():
    """Verify participant attendance"""
    data = request.json
    
    if not data:
        return jsonify({
            'success': False,
            'message': 'No data provided'
        }), 400
    
    unique_id = data.get('unique_id')
    session_time = data.get('session_time')
    
    if not unique_id or not session_time:
        return jsonify({
            'success': False,
            'message': 'Missing required information. Both unique_id and session_time are required.'
        }), 400
    
    verifier = AttendanceVerifier()
    result = verifier.verify_attendance(unique_id, session_time)
    
    return jsonify(result)


@check_in_bp.route('/history/<unique_id>')
def attendance_history(unique_id):
    """Get attendance history for a participant"""
    verifier = AttendanceVerifier()
    result = verifier.get_participant_attendance_history(unique_id)
    
    return jsonify(result)


@check_in_bp.route('/sessions')
def available_sessions():
    """Get available sessions for today"""
    verifier = AttendanceVerifier()
    
    # Determine if it's Saturday or Sunday
    if verifier.is_saturday():
        sessions = current_app.config['SATURDAY_SESSIONS']
        day = 'Saturday'
    else:
        sessions = current_app.config['SUNDAY_SESSIONS']
        day = 'Sunday'
    
    return jsonify({
        'success': True,
        'day': day,
        'sessions': sessions
    })
