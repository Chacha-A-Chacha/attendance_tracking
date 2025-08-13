from flask import Blueprint, render_template, request, jsonify, current_app, session as flask_session, redirect, url_for
from app.services.verification import AttendanceVerifier
from app.models import Session
from datetime import datetime
import calendar

check_in_bp = Blueprint('check_in', __name__)


@check_in_bp.route('/')
def scanner():
    """Display QR code scanner interface with available sessions"""
    # Get current date and day name
    today = datetime.now()
    day_name = calendar.day_name[today.weekday()]

    # For testing purposes, allow override of day
    test_day = request.args.get('test_day')
    if test_day and test_day.lower() in ['saturday', 'sunday']:
        day_name = test_day.capitalize()

    # Determine if we're checking Saturday or Sunday sessions
    is_saturday = day_name == 'Saturday'
    is_sunday = day_name == 'Sunday'
    is_weekend = is_saturday or is_sunday

    # If not weekend, default to Saturday for testing
    if not is_weekend:
        current_app.logger.info(f"Note: Today is {day_name}, not a weekend. Defaulting to Saturday for testing.")
        day_name = 'Saturday'
        is_saturday = True

    # Get current time for highlighting current session
    current_time = today.strftime('%H:%M')

    # Get all sessions for the appropriate day
    if is_saturday:
        sessions = Session.query.filter_by(day='Saturday').order_by(Session.time_slot).all()
    else:
        sessions = Session.query.filter_by(day='Sunday').order_by(Session.time_slot).all()

    # Identify current or upcoming session
    current_session = None
    upcoming_sessions = []

    for session in sessions:
        # Extract session start time for comparison (e.g., "10.00am - 11.30am" -> "10.00am")
        start_time_str = session.time_slot.split(' - ')[0]

        # Convert to 24-hour format for comparison
        if 'am' in start_time_str.lower():
            hour, minute = start_time_str.replace('am', '').split('.')
            start_hour = int(hour)
            if start_hour == 12:  # Handle 12am as 0
                start_hour = 0
        else:
            hour, minute = start_time_str.replace('pm', '').split('.')
            start_hour = int(hour)
            if start_hour < 12:  # Handle 1pm-11pm
                start_hour += 12

        start_time = f"{start_hour:02d}:{minute}"

        # Get end time for determining current session
        end_time_str = session.time_slot.split(' - ')[1]
        if 'am' in end_time_str.lower():
            hour, minute = end_time_str.replace('am', '').split('.')
            end_hour = int(hour)
            if end_hour == 12:  # Handle 12am as 0
                end_hour = 0
        else:
            hour, minute = end_time_str.replace('pm', '').split('.')
            end_hour = int(hour)
            if end_hour < 12:  # Handle 1pm-11pm
                end_hour += 12

        end_time = f"{end_hour:02d}:{minute}"

        # Check if this is the current session
        if start_time <= current_time <= end_time:
            current_session = session

        # Add to upcoming sessions if it's in the future
        if current_time < start_time:
            upcoming_sessions.append(session)

    # If no current session, use the next upcoming one
    if not current_session and upcoming_sessions:
        current_session = upcoming_sessions[0]

    # If still no current session, use the first session of the day
    if not current_session and sessions:
        current_session = sessions[0]

    # Get previous scans from session if available
    recent_scans = flask_session.get('recent_scans', [])

    # Pass all necessary data to the template
    return render_template('check_in/scanner.html',
                           day_name=day_name,
                           current_time=current_time,
                           sessions=sessions,
                           current_session=current_session,
                           recent_scans=recent_scans)


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

    # Create verification service
    verifier = AttendanceVerifier()

    # Log this verification attempt
    current_app.logger.info(
        f"Verification attempt: ID={unique_id}, Session={session_time}, Day={verifier.get_current_day_name()}")

    # Process verification
    result = verifier.verify_attendance(unique_id, session_time)

    # Store recent scans in session for display
    recent_scans = flask_session.get('recent_scans', [])

    # Add current scan to the list
    scan_entry = {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'id': unique_id,
        'name': result.get('participant', {}).get('name', 'Unknown'),
        'status': 'Correct' if result.get('success', False) else 'Incorrect',
        'message': result.get('message', '')
    }

    # Add scan to beginning of list and limit to 10 entries
    recent_scans.insert(0, scan_entry)
    recent_scans = recent_scans[:10]

    # Save back to session
    flask_session['recent_scans'] = recent_scans

    return jsonify(result)


@check_in_bp.route('/sessions')
def available_sessions():
    """Get available sessions for today"""
    # Create verification service to determine day
    verifier = AttendanceVerifier()

    # Allow day override for testing
    test_day = request.args.get('day')
    if test_day and test_day.lower() in ['saturday', 'sunday']:
        day = test_day.capitalize()
    else:
        # Determine if it's Saturday or Sunday
        day = "Saturday" if verifier.is_saturday() else "Sunday"
        if not (verifier.is_saturday() or verifier.is_sunday()):
            # If not weekend, default to current day for display but notify
            current_app.logger.info(f"Note: Today is not a weekend. Using {day} for testing.")

    # Get sessions for this day
    sessions = Session.query.filter_by(day=day).order_by(Session.time_slot).all()

    # Format for display
    session_list = [
        {
            'id': session.id,
            'time_slot': session.time_slot,
            'display_text': f"{session.time_slot}"
        }
        for session in sessions
    ]

    return jsonify({
        'success': True,
        'day': day,
        'sessions': session_list
    })


@check_in_bp.route('/clear-history')
def clear_history():
    """Clear the recent scans history"""
    flask_session['recent_scans'] = []
    return redirect(url_for('check_in.scanner'))
