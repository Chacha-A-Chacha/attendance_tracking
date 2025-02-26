from flask import Blueprint, render_template, request, jsonify
from models.participant import Participant
from services.verification import verify_attendance

check_in_bp = Blueprint('check_in', __name__)

@check_in_bp.route('/')
def scanner():
    """Display QR code scanner interface"""
    return render_template('check_in/scanner.html')

@check_in_bp.route('/verify', methods=['POST'])
def verify():
    """Verify participant attendance"""
    unique_id = request.json.get('unique_id')
    session_time = request.json.get('session_time')
    
    if not unique_id or not session_time:
        return jsonify({
            'success': False,
            'message': 'Missing required information'
        }), 400
        
    result = verify_attendance(unique_id, session_time)
    return jsonify(result)
