import os

from flask import Blueprint, render_template, request, jsonify, flash, url_for, redirect, session as flask_session
from flask import current_app

from datetime import datetime

from app import db
from app import email_service
from models import Participant, Session
from services.qrcode_generator import QRCodeGenerator
from utils.enhanced_email import Priority

participant_bp = Blueprint('participant', __name__)


@participant_bp.route('/')
def landing():
    """Landing page for participants"""
    return render_template('participant/landing.html')


@participant_bp.route('/verify', methods=['POST'])
def verify():
    """Verify participant identity"""
    email = request.form.get('email', '').strip().lower()
    unique_id = request.form.get('unique_id', '').strip()

    # Validate inputs
    if not email or not unique_id:
        flash('Please provide both email and ID', 'error')
        return redirect(url_for('participant.landing'))

    # Look up participant
    participant = Participant.query.filter_by(
        email=email,
        unique_id=unique_id
    ).first()

    if not participant:
        flash('Invalid email or ID. Please try again.', 'error')
        return redirect(url_for('participant.landing'))

    # Store participant info in session
    flask_session['participant_id'] = participant.id
    flask_session['participant_verified'] = True
    flask_session['verification_time'] = datetime.now().timestamp()

    # Redirect to participant dashboard
    return redirect(url_for('participant.dashboard'))


@participant_bp.route('/dashboard')
def dashboard():
    """Participant dashboard - requires verification"""
    # Check if participant is verified
    if not flask_session.get('participant_verified', False):
        flash('Please verify your identity first', 'error')
        return redirect(url_for('participant.landing'))

    # Check if verification has expired (30 minutes)
    verification_time = flask_session.get('verification_time', 0)
    current_time = datetime.now().timestamp()
    if (current_time - verification_time) > 1800:  # 30 minutes
        # Clear session
        flask_session.pop('participant_verified', None)
        flask_session.pop('participant_id', None)
        flask_session.pop('verification_time', None)

        flash('Your session has expired. Please verify again.', 'error')
        return redirect(url_for('participant_bp.landing'))

    # Get participant data
    participant_id = flask_session.get('participant_id')
    participant = Participant.query.get(participant_id)

    if not participant:
        flask_session.clear()
        flash('Participant not found. Please verify again.', 'error')
        return redirect(url_for('participant.landing'))

    # Get session information
    saturday_session = Session.query.get(participant.saturday_session_id)
    sunday_session = Session.query.get(participant.sunday_session_id)

    return render_template('participant/dashboard.html',
                           participant=participant,
                           saturday_session=saturday_session,
                           sunday_session=sunday_session,
                           current_time=int(current_time))  # Add current time for session timer


@participant_bp.route('/email-qrcode', methods=['POST'])
def email_qrcode():
    """Email QR code to participant"""
    # Check if participant is verified
    if not flask_session.get('participant_verified', False):
        return jsonify({
            'success': False,
            'message': 'Unauthorized'
        }), 401
    
    # Get participant
    participant_id = flask_session.get('participant_id')
    participant = Participant.query.get(participant_id)
    
    if not participant:
        return jsonify({
            'success': False,
            'message': 'Participant not found'
        }), 404
    
    # Check if QR code exists
    if not participant.qrcode_path or not os.path.exists(participant.qrcode_path):
        return jsonify({
            'success': False,
            'message': 'QR code not found. Please generate one first.'
        }), 404
    
    try:
        # Send QR code via email        
        task_id = email_service.send_qr_code(
            recipient=participant.email,
            participant=participant,
            priority=Priority.HIGH
        )
        
        # Record the email task
        # participant.last_qrcode_email = datetime.now()
        # db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'QR code has been sent to your email',
            'task_id': task_id
        })
    except Exception as e:
        current_app.logger.error(f"Error sending email: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error sending email: {str(e)}'
        }), 500


@participant_bp.route('/generate-qrcode', methods=['POST'])
def generate_qrcode():
    """Generate QR code for participant"""
    # Check if participant is verified
    if not flask_session.get('participant_verified', False):
        return jsonify({
            'success': False,
            'message': 'Unauthorized'
        }), 401

    # Get participant
    participant_id = flask_session.get('participant_id')
    participant = Participant.query.get(participant_id)

    if not participant:
        return jsonify({
            'success': False,
            'message': 'Participant not found'
        }), 404

    try:
        # Generate QR code
        qr_generator = QRCodeGenerator()
        qr_path = qr_generator.generate_for_participant(participant)

        # Update participant record
        participant.qrcode_path = qr_path
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'QR code generated successfully'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating QR code: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error generating QR code. Please try again later.'
        }), 500


@participant_bp.route('/attendance-history')
def get_attendance_history():
    """Get attendance history for participant"""
    # Check if participant is verified
    if not flask_session.get('participant_verified', False):
        return jsonify({
            'success': False,
            'message': 'Unauthorized'
        }), 401

    # Get participant
    participant_id = flask_session.get('participant_id')
    participant = Participant.query.get(participant_id)

    if not participant:
        return jsonify({
            'success': False,
            'message': 'Participant not found'
        }), 404

    # Initialize the attendance verifier
    from services.verification import AttendanceVerifier
    verifier = AttendanceVerifier()

    # Get attendance history
    result = verifier.get_participant_attendance_history(participant.unique_id)

    return jsonify(result)


@participant_bp.route('/logout')
def logout():
    """Log out participant"""
    flask_session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('participant.landing'))


@participant_bp.route('/participant/<int:participant_id>', methods=['GET'])
def get_participant_info(participant_id):
    participant = Participant.query.get(participant_id)
    if participant:
        return render_template('participant/info.html', participant=participant)
    return jsonify({'error': 'Participant not found'}), 404


@participant_bp.route('/participant', methods=['POST'])
def create_participant():
    data = request.json
    new_participant = Participant(name=data['name'], email=data['email'])
    new_participant.save()
    return jsonify({'message': 'Participant created successfully'}), 201


@participant_bp.route('/participant/<int:participant_id>', methods=['PUT'])
def update_participant(participant_id):
    participant = Participant.query.get(participant_id)
    if not participant:
        return jsonify({'error': 'Participant not found'}), 404

    data = request.json
    participant.name = data.get('name', participant.name)
    participant.email = data.get('email', participant.email)
    participant.save()
    return jsonify({'message': 'Participant updated successfully'}), 200


@participant_bp.route('/participant/<int:participant_id>', methods=['DELETE'])
def delete_participant(participant_id):
    participant = Participant.query.get(participant_id)
    if not participant:
        return jsonify({'error': 'Participant not found'}), 404

    participant.delete()
    return jsonify({'message': 'Participant deleted successfully'}), 200
