from flask import Blueprint, request, jsonify, render_template
from services.verification import verify_attendance

check_in_bp = Blueprint('check_in', __name__)

@check_in_bp.route('/check-in', methods=['GET'])
def scanner():
    return render_template('check_in/scanner.html')

@check_in_bp.route('/check-in/verify', methods=['POST'])
def verify():
    qr_code_data = request.json.get('qr_code')
    result = verify_attendance(qr_code_data)
    return jsonify(result)