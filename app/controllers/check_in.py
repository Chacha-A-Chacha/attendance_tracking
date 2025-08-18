# routes/check_in.py
"""
Check-in routes for QR code scanning and attendance verification.
Handles both QR code JSON scanning and manual unique ID entry with real-time updates.
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, current_app, session as flask_session, flash
from app.services.attendance_service import AttendanceService
from app.services.session_classroom_service import SessionClassroomService
from app.models.session import Session
from app.extensions import db

# Initialize blueprint
check_in_bp = Blueprint('check_in', __name__)

logger = logging.getLogger('check_in')


@check_in_bp.route('/')
def scanner():
    """
    Enhanced QR scanner interface with session timing intelligence and real-time data.
    Displays available sessions, current session detection, and attendance progress.
    """
    try:
        # Get current date and time for session detection
        current_time = datetime.now()
        day_name = current_time.strftime('%A')

        # Allow day override for testing
        test_day = request.args.get('test_day')
        if test_day and test_day.lower() in ['saturday', 'sunday']:
            day_name = test_day.capitalize()
            logger.info(f"Using test day override: {day_name}")

        # Default to Saturday for testing if not weekend
        if day_name not in ['Saturday', 'Sunday']:
            logger.info(f"Note: Today is {day_name}, not a weekend. Defaulting to Saturday for testing.")
            day_name = 'Saturday'

        # Get all sessions for the current day with optimized query
        sessions = (
            db.session.query(Session)
            .filter_by(day=day_name)
            .order_by(Session.time_slot)
            .all()
        )

        if not sessions:
            logger.warning(f"No sessions found for {day_name}")
            flash(f'No sessions configured for {day_name}', 'warning')

        # Determine current and upcoming sessions with timing intelligence
        current_session_data = _detect_current_session(sessions, current_time)

        # Get real-time attendance statistics for current session
        attendance_stats = {}
        if current_session_data['current_session']:
            stats_result = AttendanceService.get_real_time_attendance_stats(
                session_id=current_session_data['current_session'].id
            )
            if stats_result['success']:
                attendance_stats = stats_result

        # Get recent scans from session
        recent_scans = flask_session.get('recent_scans', [])

        # Format sessions for template with timing information
        session_list = []
        for session in sessions:
            session_timing = _parse_session_timing(session.time_slot)
            session_list.append({
                'id': session.id,
                'time_slot': session.time_slot,
                'day': session.day,
                'start_time': session_timing['start_time'],
                'end_time': session_timing['end_time'],
                'is_current': current_session_data['current_session'] and
                              current_session_data['current_session'].id == session.id,
                'is_upcoming': session in current_session_data['upcoming_sessions'],
                'minutes_until_start': session_timing['minutes_until_start'],
                'minutes_until_end': session_timing['minutes_until_end']
            })

        template_data = {
            'day_name': day_name,
            'current_time': current_time.strftime('%H:%M'),
            'current_date': current_time.strftime('%Y-%m-%d'),
            'sessions': session_list,
            'current_session': current_session_data['current_session'],
            'upcoming_sessions': current_session_data['upcoming_sessions'],
            'recent_scans': recent_scans,
            'attendance_stats': attendance_stats,
            'session_progress': current_session_data.get('progress', 0)
        }

        logger.info(f"Scanner page loaded for {day_name} with {len(sessions)} sessions")
        return render_template('check_in/scanner.html', **template_data)

    except Exception as e:
        logger.error(f"Error loading scanner page: {str(e)}", exc_info=True)
        flash('Error loading scanner interface', 'error')
        return render_template('check_in/scanner.html',
                               sessions=[],
                               current_session=None,
                               recent_scans=[])


@check_in_bp.route('/verify', methods=['POST'])
def verify():
    """
    Enhanced attendance verification handling both QR JSON and manual unique ID entry.
    Supports real-time updates and comprehensive error handling.
    """
    try:
        # Extract and validate request data
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided',
                'error_code': 'missing_data'
            }), 400

        # Extract identifiers and session information
        qr_data = data.get('qr_data')  # JSON string from QR code
        unique_id = data.get('unique_id')  # Manual 5-digit entry
        session_identifier = data.get('session_time') or data.get('session_id')

        if not session_identifier:
            return jsonify({
                'success': False,
                'message': 'Session information is required',
                'error_code': 'missing_session'
            }), 400

        # Parse identifier from QR code JSON or manual entry
        participant_identifier = None
        check_in_method = 'manual'

        if qr_data:
            # Handle QR code with JSON data
            try:
                qr_json = json.loads(qr_data)
                # Prefer UUID id, fallback to unique_id
                participant_identifier = qr_json.get('id') or qr_json.get('unique_id')
                check_in_method = 'qr_code'
                logger.info(f"QR scan processed: {qr_json}")
            except json.JSONDecodeError:
                # Handle plain text QR codes (legacy support)
                participant_identifier = qr_data
                check_in_method = 'qr_code'
                logger.info(f"Plain text QR code: {qr_data}")

        elif unique_id:
            # Handle manual 5-digit entry
            if len(unique_id.strip()) == 5 and unique_id.strip().isdigit():
                participant_identifier = unique_id.strip()
                check_in_method = 'manual'
            else:
                return jsonify({
                    'success': False,
                    'message': 'Manual entry must be exactly 5 digits',
                    'error_code': 'invalid_format'
                }), 400

        if not participant_identifier:
            return jsonify({
                'success': False,
                'message': 'Valid participant identifier is required',
                'error_code': 'missing_identifier'
            }), 400

        # Log verification attempt
        logger.info(f"Attendance verification: ID={participant_identifier}, "
                    f"Session={session_identifier}, Method={check_in_method}")

        # Process verification using AttendanceService
        result = AttendanceService.verify_and_record_attendance(
            unique_id=participant_identifier,
            session_identifier=session_identifier,
            check_in_method=check_in_method
        )

        # Update recent scans in flask session for UI display
        _update_recent_scans(participant_identifier, result, check_in_method)

        # Add additional UI-specific data
        if result.get('success'):
            result['ui_status'] = 'success'
            result['ui_message'] = result.get('message', 'Attendance verified successfully')
        else:
            result['ui_status'] = 'error'
            result['ui_message'] = result.get('message', 'Verification failed')

        # Add session progress information if this was successful attendance
        if result.get('success') and result.get('session'):
            session_id = result['session']['id']
            progress_data = _get_session_progress_data(session_id)
            result['session_progress'] = progress_data

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error during attendance verification: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Server error during verification',
            'error_code': 'server_error',
            'ui_status': 'error',
            'ui_message': 'Connection error. Please try again.'
        }), 500


@check_in_bp.route('/bulk-absence/<int:session_id>', methods=['POST'])
def mark_bulk_absences(session_id):
    """
    Mark bulk absences for a session when it's ending.
    Triggered manually or automatically when session time is almost over.
    """
    try:
        # Get optional parameters
        data = request.get_json() or {}
        attendance_date = data.get('date')  # Optional specific date
        force_mark = data.get('force', False)  # Force marking even if session not ending

        # Validate session exists
        session = db.session.query(Session).filter_by(id=session_id).first()
        if not session:
            return jsonify({
                'success': False,
                'message': 'Session not found',
                'error_code': 'session_not_found'
            }), 404

        # Check if session is ending soon (unless force is specified)
        if not force_mark:
            session_timing = _parse_session_timing(session.time_slot)
            minutes_until_end = session_timing['minutes_until_end']

            # Only allow bulk marking if session is ending within 30 minutes or has ended
            if minutes_until_end > 30:
                return jsonify({
                    'success': False,
                    'message': f'Session ends in {minutes_until_end} minutes. Bulk marking not allowed yet.',
                    'error_code': 'session_not_ending',
                    'minutes_until_end': minutes_until_end
                }), 400

        # Perform bulk absence marking
        result = AttendanceService.bulk_mark_absences(
            session_id=session_id,
            attendance_date=attendance_date,
            admin_user_id=None,  # Could be added if admin authentication is implemented
            exclude_existing=True
        )

        if result['success']:
            logger.info(f"Bulk absences marked for session {session_id}: "
                        f"{result['statistics']['marked_absent']} participants")

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error marking bulk absences for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Error marking bulk absences',
            'error_code': 'server_error'
        }), 500


@check_in_bp.route('/session-status/<int:session_id>')
def session_status(session_id):
    """
    Get real-time session status including timing, attendance stats, and progress.
    Used for periodic updates on the scanner interface.
    """
    try:
        # Get session with validation
        session = db.session.query(Session).filter_by(id=session_id).first()
        if not session:
            return jsonify({
                'success': False,
                'message': 'Session not found',
                'error_code': 'session_not_found'
            }), 404

        # Get session timing information
        session_timing = _parse_session_timing(session.time_slot)

        # Get real-time attendance statistics
        attendance_stats = AttendanceService.get_real_time_attendance_stats(session_id=session_id)

        # Get session progress data
        progress_data = _get_session_progress_data(session_id)

        # Determine if bulk absence marking should be available
        can_mark_absences = session_timing['minutes_until_end'] <= 30

        result = {
            'success': True,
            'session': {
                'id': session.id,
                'time_slot': session.time_slot,
                'day': session.day
            },
            'timing': session_timing,
            'attendance_stats': attendance_stats,
            'progress': progress_data,
            'can_mark_absences': can_mark_absences,
            'current_time': datetime.now().strftime('%H:%M:%S')
        }

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting session status for {session_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Error retrieving session status',
            'error_code': 'server_error'
        }), 500


@check_in_bp.route('/sessions/current')
def get_current_sessions():
    """
    Get current and upcoming sessions for the day with real-time information.
    Used for dynamic session selection and status updates.
    """
    try:
        current_time = datetime.now()
        day_name = current_time.strftime('%A')

        # Allow day override for testing
        test_day = request.args.get('day')
        if test_day and test_day.lower() in ['saturday', 'sunday']:
            day_name = test_day.capitalize()

        # Default to Saturday for testing if not weekend
        if day_name not in ['Saturday', 'Sunday']:
            day_name = 'Saturday'

        # Get sessions for the day
        sessions = (
            db.session.query(Session)
            .filter_by(day=day_name)
            .order_by(Session.time_slot)
            .all()
        )

        # Process session timing and status
        session_data = []
        current_session = None

        for session in sessions:
            timing = _parse_session_timing(session.time_slot)

            # Get attendance stats for this session
            stats_result = AttendanceService.get_real_time_attendance_stats(session_id=session.id)
            attendance_stats = stats_result if stats_result['success'] else {}

            session_info = {
                'id': session.id,
                'time_slot': session.time_slot,
                'day': session.day,
                'timing': timing,
                'attendance_stats': attendance_stats,
                'is_current': timing['is_current'],
                'is_upcoming': timing['is_upcoming'],
                'can_mark_absences': timing['minutes_until_end'] <= 30
            }

            session_data.append(session_info)

            if timing['is_current']:
                current_session = session_info

        return jsonify({
            'success': True,
            'day': day_name,
            'current_time': current_time.strftime('%H:%M:%S'),
            'sessions': session_data,
            'current_session': current_session
        })

    except Exception as e:
        logger.error(f"Error getting current sessions: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Error retrieving session information',
            'error_code': 'server_error'
        }), 500


@check_in_bp.route('/clear-history')
def clear_scan_history():
    """Clear recent scan history from the session."""
    flask_session['recent_scans'] = []
    logger.info("Scan history cleared")
    return jsonify({'success': True, 'message': 'Scan history cleared'})


# Helper Functions

def _detect_current_session(sessions, current_time):
    """
    Detect current and upcoming sessions based on time analysis.
    Returns session data with timing information.
    """
    current_session = None
    upcoming_sessions = []
    progress = 0

    for session in sessions:
        timing = _parse_session_timing(session.time_slot)

        if timing['is_current']:
            current_session = session
            progress = timing['progress_percentage']
        elif timing['is_upcoming']:
            upcoming_sessions.append(session)

    # If no current session, use the next upcoming one
    if not current_session and upcoming_sessions:
        current_session = upcoming_sessions[0]

    # If still no current session, use the first session of the day
    if not current_session and sessions:
        current_session = sessions[0]

    return {
        'current_session': current_session,
        'upcoming_sessions': upcoming_sessions,
        'progress': progress
    }


def _parse_session_timing(time_slot):
    """
    Parse session time slot string and calculate timing information.
    Handles formats like "10.00am - 11.30am" or "2.00pm - 3.30pm"
    """
    try:
        # Split time slot into start and end times
        start_str, end_str = time_slot.split(' - ')

        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute
        current_total_minutes = current_hour * 60 + current_minute

        # Parse start time
        start_time_minutes = _parse_time_to_minutes(start_str.strip())
        end_time_minutes = _parse_time_to_minutes(end_str.strip())

        # Calculate timing information
        minutes_until_start = start_time_minutes - current_total_minutes
        minutes_until_end = end_time_minutes - current_total_minutes

        # Determine session status
        is_current = start_time_minutes <= current_total_minutes <= end_time_minutes
        is_upcoming = current_total_minutes < start_time_minutes
        is_past = current_total_minutes > end_time_minutes

        # Calculate progress percentage for current session
        progress_percentage = 0
        if is_current:
            session_duration = end_time_minutes - start_time_minutes
            elapsed = current_total_minutes - start_time_minutes
            progress_percentage = min(100, max(0, (elapsed / session_duration) * 100))

        return {
            'start_time': start_str.strip(),
            'end_time': end_str.strip(),
            'start_minutes': start_time_minutes,
            'end_minutes': end_time_minutes,
            'minutes_until_start': minutes_until_start,
            'minutes_until_end': minutes_until_end,
            'is_current': is_current,
            'is_upcoming': is_upcoming,
            'is_past': is_past,
            'progress_percentage': round(progress_percentage, 1)
        }

    except Exception as e:
        logger.error(f"Error parsing session timing for '{time_slot}': {str(e)}")
        return {
            'start_time': time_slot,
            'end_time': time_slot,
            'minutes_until_start': 0,
            'minutes_until_end': 0,
            'is_current': False,
            'is_upcoming': False,
            'is_past': False,
            'progress_percentage': 0
        }


def _parse_time_to_minutes(time_str):
    """
    Convert time string like "10.00am" or "2.30pm" to total minutes from midnight.
    """
    time_str = time_str.lower()

    # Handle am/pm
    is_pm = 'pm' in time_str
    time_str = time_str.replace('am', '').replace('pm', '').strip()

    # Split hour and minute
    hour_str, minute_str = time_str.split('.')
    hour = int(hour_str)
    minute = int(minute_str)

    # Convert to 24-hour format
    if is_pm and hour != 12:
        hour += 12
    elif not is_pm and hour == 12:
        hour = 0

    return hour * 60 + minute


def _update_recent_scans(participant_identifier, verification_result, check_in_method):
    """
    Update recent scans in flask session for UI display.
    """
    try:
        recent_scans = flask_session.get('recent_scans', [])

        # Get participant name from verification result
        participant_name = 'Unknown'
        if verification_result.get('participant'):
            participant_name = verification_result['participant'].get('full_name', 'Unknown')

        # Create scan entry
        scan_entry = {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'identifier': participant_identifier,
            'name': participant_name,
            'method': check_in_method,
            'status': 'Success' if verification_result.get('success') else 'Failed',
            'message': verification_result.get('message', ''),
            'is_correct_session': verification_result.get('is_correct_session', False)
        }

        # Add to beginning of list and limit to 10 entries
        recent_scans.insert(0, scan_entry)
        recent_scans = recent_scans[:10]

        # Save back to session
        flask_session['recent_scans'] = recent_scans
        flask_session.modified = True

    except Exception as e:
        logger.error(f"Error updating recent scans: {str(e)}")


def _get_session_progress_data(session_id):
    """
    Get comprehensive progress data for a session.
    """
    try:
        # Get session information
        session = db.session.query(Session).filter_by(id=session_id).first()
        if not session:
            return {}

        # Get timing information
        timing = _parse_session_timing(session.time_slot)

        # Get attendance statistics
        stats_result = AttendanceService.get_real_time_attendance_stats(session_id=session_id)

        progress_data = {
            'session_id': session_id,
            'timing': timing,
            'attendance_stats': stats_result if stats_result.get('success') else {},
            'can_mark_absences': timing['minutes_until_end'] <= 30,
            'auto_mark_threshold': 30  # Minutes before end to allow bulk marking
        }

        return progress_data

    except Exception as e:
        logger.error(f"Error getting session progress data: {str(e)}")
        return {}
