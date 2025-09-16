# controllers/participant_portal.py
"""
Participant Portal Routes - AJAX-optimized with proper data structures.
"""

import os
from flask import Blueprint, render_template, request, jsonify, current_user, send_file, flash, redirect, url_for
from flask_login import login_required
from werkzeug.exceptions import NotFound

from app.services.participants_service import ParticipantsService
from app.services.qr_code_service import QRCodeService
from app.services.session_classroom_service import SessionClassroomService
from app.utils.auth import student_or_staff_required, role_required
from app.models.user import RoleType
from app.models.session import Session
from app.extensions import db

from . import participant_portal_bp

# ===============================
# TEMPLATE ROUTES (3 Main Templates)
# ===============================

@participant_portal_bp.route('/dashboard')
@login_required
@student_or_staff_required
def dashboard():
    """Main dashboard template with AJAX placeholders."""
    if not current_user.participant_id:
        flash('No participant record found', 'error')
        return redirect(url_for('auth.login'))

    # Basic template context
    context = {
        'user_roles': [role.name for role in current_user.roles],
        'is_student_rep': current_user.has_role(RoleType.STUDENT_REPRESENTATIVE),
        'participant_id': current_user.participant_id
    }

    return render_template('participant_portal/dashboard.html', **context)


@participant_portal_bp.route('/attendance')
@login_required
@student_or_staff_required
def attendance():
    """Attendance records template with AJAX placeholders."""
    if not current_user.participant_id:
        flash('No participant record found', 'error')
        return redirect(url_for('participant_portal.dashboard'))

    context = {
        'participant_id': current_user.participant_id
    }

    return render_template('participant_portal/attendance.html', **context)


@participant_portal_bp.route('/students')
@login_required
@role_required(RoleType.STUDENT_REPRESENTATIVE)
def students():
    """Student list template for representatives with AJAX placeholders."""
    if not current_user.participant_id:
        flash('No participant record found', 'error')
        return redirect(url_for('participant_portal.dashboard'))

    context = {
        'rep_participant_id': current_user.participant_id
    }

    return render_template('participant_portal/students.html', **context)


# ===============================
# PROFILE & DASHBOARD APIs
# ===============================

@participant_portal_bp.route('/api/profile/data')
@login_required
@student_or_staff_required
def get_profile_data():
    """Get profile data for AJAX consumption."""
    try:
        result = ParticipantsService.get_participant_profile(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving profile data'
        }), 500


@participant_portal_bp.route('/api/dashboard/data')
@login_required
@student_or_staff_required
def get_dashboard_data():
    """Get comprehensive dashboard data for AJAX consumption."""
    try:
        result = ParticipantsService.get_participant_dashboard_data(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving dashboard data'
        }), 500


@participant_portal_bp.route('/api/profile/photo/upload', methods=['POST'])
@login_required
@student_or_staff_required
def upload_profile_photo():
    """Upload profile photo via AJAX."""
    try:
        if 'photo' not in request.files:
            return jsonify({
                'success': False,
                'error_code': 'missing_file',
                'message': 'No file uploaded'
            }), 400

        photo_file = request.files['photo']

        result = ParticipantsService.upload_profile_photo(
            participant_id=current_user.participant_id,
            photo_file=photo_file,
            requesting_user_id=current_user.id
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error uploading photo'
        }), 500


@participant_portal_bp.route('/api/profile/photo', methods=['DELETE'])
@login_required
@student_or_staff_required
def delete_profile_photo():
    """Delete profile photo via AJAX."""
    try:
        result = ParticipantsService.delete_profile_photo(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error deleting photo'
        }), 500


# ===============================
# QR CODE APIs (Enhanced)
# ===============================

@participant_portal_bp.route('/api/qr-code/info')
@login_required
@student_or_staff_required
def get_qr_info():
    """Get QR code information for AJAX consumption."""
    try:
        result = QRCodeService.get_participant_qr_info(
            participant_id=current_user.participant_id,
            user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving QR info'
        }), 500


@participant_portal_bp.route('/api/qr-code/generate', methods=['POST'])
@login_required
@student_or_staff_required
def generate_qr_code():
    """Generate QR code via AJAX."""
    try:
        result = QRCodeService.generate_for_participant(
            participant_id=current_user.participant_id,
            user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error generating QR code'
        }), 500


@participant_portal_bp.route('/api/qr-code/regenerate', methods=['POST'])
@login_required
@student_or_staff_required
def regenerate_qr_code():
    """Regenerate QR code via AJAX."""
    try:
        result = QRCodeService.regenerate_for_participant(
            participant_id=current_user.participant_id,
            user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error regenerating QR code'
        }), 500


@participant_portal_bp.route('/api/qr-code/download')
@login_required
@student_or_staff_required
def download_qr_code():
    """Download QR code as file."""
    try:
        qr_info = QRCodeService.get_participant_qr_info(
            participant_id=current_user.participant_id,
            user_id=current_user.id
        )

        if not qr_info['success'] or not qr_info.get('qr_path'):
            return jsonify({
                'success': False,
                'error_code': 'qr_not_available',
                'message': 'QR code not available for download'
            }), 404

        return send_file(
            qr_info['qr_path'],
            as_attachment=True,
            download_name=f"qr_code_{current_user.participant.unique_id}.png"
        )
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error downloading QR code'
        }), 500


# ===============================
# ATTENDANCE APIs
# ===============================

@participant_portal_bp.route('/api/attendance/summary')
@login_required
@student_or_staff_required
def get_attendance_summary():
    """Get attendance summary for AJAX consumption."""
    try:
        date_range = None
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if start_date and end_date:
            from datetime import datetime
            date_range = (
                datetime.strptime(start_date, '%Y-%m-%d').date(),
                datetime.strptime(end_date, '%Y-%m-%d').date()
            )

        result = ParticipantsService.get_attendance_summary(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id,
            date_range=date_range
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving attendance summary'
        }), 500


@participant_portal_bp.route('/api/attendance/history')
@login_required
@student_or_staff_required
def get_attendance_history():
    """Get paginated attendance history for AJAX consumption."""
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)

        result = ParticipantsService.get_attendance_history(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id,
            limit=limit,
            page=page
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving attendance history'
        }), 500


@participant_portal_bp.route('/api/attendance/issues')
@login_required
@student_or_staff_required
def get_attendance_issues():
    """Get attendance issues and warnings for AJAX consumption."""
    try:
        result = ParticipantsService.get_attendance_issues(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving attendance issues'
        }), 500


@participant_portal_bp.route('/api/attendance/calendar-data')
@login_required
@student_or_staff_required
def get_attendance_calendar_data():
    """Get attendance data for calendar view."""
    try:
        month = request.args.get('month', type=int)
        year = request.args.get('year', type=int)

        result = ParticipantsService.get_attendance_calendar_data(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id,
            month=month,
            year=year
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving calendar data'
        }), 500


# ===============================
# SESSION REASSIGNMENT APIs
# ===============================

@participant_portal_bp.route('/api/sessions/available/<day_type>')
@login_required
@student_or_staff_required
def get_available_sessions(day_type):
    """Get available sessions for reassignment by day type."""
    try:
        if day_type not in ['Saturday', 'Sunday']:
            return jsonify({
                'success': False,
                'error_code': 'invalid_day',
                'message': 'Day type must be Saturday or Sunday'
            }), 400

        result = ParticipantsService.get_available_sessions_for_reassignment(
            participant_id=current_user.participant_id,
            day_type=day_type,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving available sessions'
        }), 500


@participant_portal_bp.route('/api/reassignment/request', methods=['POST'])
@login_required
@student_or_staff_required
def submit_reassignment_request():
    """Submit session reassignment request via AJAX."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error_code': 'missing_data',
                'message': 'Request data is required'
            }), 400

        result = ParticipantsService.submit_reassignment_request(
            participant_id=current_user.participant_id,
            day_type=data.get('day_type'),
            requested_session_id=data.get('requested_session_id'),
            reason=data.get('reason'),
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error submitting reassignment request'
        }), 500


@participant_portal_bp.route('/api/reassignment/history')
@login_required
@student_or_staff_required
def get_reassignment_history():
    """Get reassignment request history for AJAX consumption."""
    try:
        limit = request.args.get('limit', 20, type=int)

        result = ParticipantsService.get_reassignment_history(
            participant_id=current_user.participant_id,
            requesting_user_id=current_user.id,
            limit=limit
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving reassignment history'
        }), 500


@participant_portal_bp.route('/api/reassignment/status/<request_id>')
@login_required
@student_or_staff_required
def get_reassignment_status(request_id):
    """Get status of specific reassignment request."""
    try:
        result = ParticipantsService.get_reassignment_request_status(
            request_id=request_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving request status'
        }), 500


# ===============================
# STUDENT REPRESENTATIVE APIs
# ===============================

@participant_portal_bp.route('/api/representative/students')
@login_required
@role_required(RoleType.STUDENT_REPRESENTATIVE)
def get_representative_students():
    """Get students in representative's sessions for AJAX consumption."""
    try:
        session_id = request.args.get('session_id')
        day_type = request.args.get('day_type')

        result = ParticipantsService.get_session_participants(
            requesting_user_id=current_user.id,
            session_id=session_id,
            day_type=day_type
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving session participants'
        }), 500


@participant_portal_bp.route('/api/representative/sessions')
@login_required
@role_required(RoleType.STUDENT_REPRESENTATIVE)
def get_representative_sessions():
    """Get representative's session information."""
    try:
        result = ParticipantsService.get_representative_session_info(
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving session information'
        }), 500


@participant_portal_bp.route('/api/representative/check-in-url')
@login_required
@role_required(RoleType.STUDENT_REPRESENTATIVE)
def get_check_in_url():
    """Get check-in URL for representative assistance."""
    try:
        # Get current session info for redirection
        session_info = ParticipantsService.get_representative_session_info(current_user.id)

        if not session_info['success']:
            return jsonify(session_info)

        # Build check-in URL based on current time/session
        from datetime import datetime
        current_day = datetime.now().strftime('%A')

        # Determine appropriate session for current time
        check_in_url = '/check_in/'
        if current_day in ['Saturday', 'Sunday']:
            check_in_url += f'?day={current_day.lower()}'

        return jsonify({
            'success': True,
            'check_in_url': check_in_url,
            'session_info': session_info['data']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error generating check-in URL'
        }), 500


@participant_portal_bp.route('/api/representative/student/<student_id>/contact')
@login_required
@role_required(RoleType.STUDENT_REPRESENTATIVE)
def get_student_contact(student_id):
    """Get student contact information for representative."""
    try:
        result = ParticipantsService.get_student_contact_info(
            student_id=student_id,
            requesting_user_id=current_user.id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error_code': 'server_error',
            'message': 'Error retrieving student contact info'
        }), 500
