from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from app.services.importer import import_spreadsheet
from app.services.verification import AttendanceVerifier
from app.services.session_reassignment_service import SessionReassignmentService
import os
from datetime import datetime
from sqlalchemy import func
from app.extensions import db
from app.models import Participant, Session, Attendance
from app.utils.export_data import export_participants_to_excel
from app.utils.session_mapper import get_session_capacity, get_session_count
from . import admin_bp
reassignment_service = SessionReassignmentService()


@admin_bp.route('/initialize-data', methods=['GET'])
def initialize_data():
    """Initialize the system by importing the default data file"""
    data_path = os.path.join(current_app.root_path, 'data', 'sessions_data.xlsx')
    current_app.logger.info(f'Initializing data from {data_path}')

    # Check if file exists
    if not os.path.exists(data_path):
        return jsonify({
            'success': False,
            'message': f'Data file not found at {data_path}'
        }), 404

    # Import the spreadsheet
    result = import_spreadsheet(data_path)

    return jsonify(result)


@admin_bp.route('/capacities', methods=['GET'])
def get_capacities():
    """Get capacity information for classrooms and sessions"""
    # Get classroom capacities from config
    classroom_capacities = current_app.config.get('SESSION_CAPACITY', {})

    # Get all sessions
    sessions = Session.query.all()

    # Initialize data structure
    capacity_data = {
        "classroom_capacities": classroom_capacities,
        "sessions": {}
    }

    # Get laptop and no-laptop classroom IDs from config
    laptop_classroom = current_app.config['LAPTOP_CLASSROOM']
    no_laptop_classroom = current_app.config['NO_LAPTOP_CLASSROOM']

    # Calculate session counts and remaining capacity
    for session in sessions:
        session_key = f"{session.day}_{session.time_slot}"

        # Get counts for both classrooms
        laptop_count = get_session_count(session.id, laptop_classroom)
        no_laptop_count = get_session_count(session.id, no_laptop_classroom)

        # Get capacities
        laptop_capacity = get_session_capacity(laptop_classroom)
        no_laptop_capacity = get_session_capacity(no_laptop_classroom)

        # Store data
        capacity_data["sessions"][session_key] = {
            "id": session.id,
            "day": session.day,
            "time_slot": session.time_slot,
            "classrooms": {
                laptop_classroom: {
                    "capacity": laptop_capacity,
                    "current_count": laptop_count,
                    "available": laptop_capacity - laptop_count,
                    "percentage_filled": round((laptop_count / laptop_capacity) * 100, 1) if laptop_capacity > 0 else 0
                },
                no_laptop_classroom: {
                    "capacity": no_laptop_capacity,
                    "current_count": no_laptop_count,
                    "available": no_laptop_capacity - no_laptop_count,
                    "percentage_filled": round((no_laptop_count / no_laptop_capacity) * 100,
                                               1) if no_laptop_capacity > 0 else 0
                }
            },
            "total": {
                "capacity": laptop_capacity + no_laptop_capacity,
                "current_count": laptop_count + no_laptop_count,
                "available": (laptop_capacity + no_laptop_capacity) - (laptop_count + no_laptop_count),
                "percentage_filled": round(
                    ((laptop_count + no_laptop_count) / (laptop_capacity + no_laptop_capacity)) * 100, 1) if (
                                                                                                                         laptop_capacity + no_laptop_capacity) > 0 else 0
            }
        }

    # Add summary data
    capacity_data["summary"] = {
        "total_capacity": sum(classroom_capacities.values()),
        "total_registered": Participant.query.count(),
        "saturday_sessions": len([s for s in sessions if s.day == "Saturday"]),
        "sunday_sessions": len([s for s in sessions if s.day == "Sunday"])
    }

    return jsonify(capacity_data)


@admin_bp.route('/dashboard')
def dashboard():
    """Admin dashboard with attendance overview"""
    # Get current date
    today = datetime.now().date()
    day_of_week = today.strftime("%A")

    # Get all sessions
    sessions = Session.query.all()

    return render_template('admin/dashboard.html',
                           today=today,
                           day_of_week=day_of_week,
                           sessions=sessions)


@admin_bp.route('/sessions', methods=['GET'])
def get_sessions():
    """Get all available sessions"""
    try:
        sessions = Session.query.all()
        session_list = [{
            'id': session.id,
            'day': session.day,
            'time_slot': session.time_slot
        } for session in sessions]

        return jsonify({
            'success': True,
            'sessions': session_list
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving sessions: {str(e)}'
        }), 500


@admin_bp.route('/attendance/<int:session_id>', methods=['GET'])
def get_session_attendance(session_id):
    """Get attendance for a specific session on a specific date"""
    date_str = request.args.get('date')  # YYYY-MM-DD format
    include_absent = request.args.get('include_absent', 'true').lower() == 'true'

    verifier = AttendanceVerifier()
    result = verifier.get_attendance_by_session(session_id, date_str, include_absent)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(result)
    else:
        # Render template for non-AJAX requests
        session = Session.query.get(session_id)
        return render_template('admin/session_attendance.html',
                               session=session,
                               date=date_str,
                               attendance_data=result)


@admin_bp.route('/session/<int:session_id>/dates', methods=['GET'])
def get_session_dates(session_id):
    """Get all dates for which attendance was recorded for a specific session"""
    try:
        # Get unique dates for this session
        dates = db.session.query(
            func.date(Attendance.timestamp).label('date')
        ).filter(
            Attendance.session_id == session_id
        ).distinct().all()

        # Format dates
        formatted_dates = [date[0].strftime('%Y-%m-%d') for date in dates]

        return jsonify({
            '  ': True,
            'session_id': session_id,
            'dates': formatted_dates
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving dates: {str(e)}'
        }), 500


@admin_bp.route('/participant/<unique_id>/history', methods=['GET'])
def get_participant_history(unique_id):
    """Get attendance history for a participant"""
    verifier = AttendanceVerifier()
    result = verifier.get_participant_attendance_history(unique_id)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(result)
    else:
        # Render template for non-AJAX requests
        participant = Participant.query.filter_by(unique_id=unique_id).first()
        return render_template('admin/participant_history.html',
                               participant=participant,
                               attendance_data=result)


@admin_bp.route('/participant/<unique_id>/sessions', methods=['GET'])
def get_participant_sessions(unique_id):
    """Get session information for a participant"""
    try:
        participant = Participant.query.filter_by(unique_id=unique_id).first()

        if not participant:
            return jsonify({
                'success': False,
                'message': 'Participant not found'
            }), 404

        # Get session info
        saturday_session = Session.query.get(participant.saturday_session_id)
        sunday_session = Session.query.get(participant.sunday_session_id)

        return jsonify({
            'success': True,
            'participant_id': participant.id,
            'saturday_session': saturday_session.time_slot if saturday_session else None,
            'sunday_session': sunday_session.time_slot if sunday_session else None
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving participant sessions: {str(e)}'
        }), 500


@admin_bp.route('/session/<int:session_id>/mark-absent', methods=['POST'])
def mark_absent(session_id):
    """Mark expected but unrecorded participants as absent for a session"""
    date_str = request.json.get('date')  # YYYY-MM-DD format

    verifier = AttendanceVerifier()
    result = verifier.mark_absent_participants(session_id, date_str)

    return jsonify(result)


@admin_bp.route('/attendance/summary', methods=['GET'])
def get_attendance_summary():
    """Get attendance summary for all sessions on a specific date"""
    date_str = request.args.get('date')  # YYYY-MM-DD format

    try:
        # Parse date
        if date_str:
            try:
                attendance_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid date format. Use YYYY-MM-DD',
                    'error_code': 'invalid_date_format'
                }), 400
        else:
            # Use current date
            attendance_date = datetime.now().date()

        # Get day of week
        day_of_week = attendance_date.strftime("%A")

        # Get sessions for this day
        sessions = Session.query.filter_by(day=day_of_week).all()

        # Initialize summary
        summary = {
            'date': date_str or attendance_date.strftime("%Y-%m-%d"),
            'day': day_of_week,
            'sessions': {},
            'total_expected': 0,
            'total_present': 0,
            'attendance_rate': 0
        }

        # Collect data for each session
        verifier = AttendanceVerifier()

        for session in sessions:
            session_data = verifier.get_attendance_by_session(session.id, date_str)

            if session_data['success']:
                summary['sessions'][session.time_slot] = {
                    'id': session.id,
                    'time_slot': session.time_slot,
                    'expected': session_data['stats']['total_expected'],
                    'present': session_data['stats']['total_present'],
                    'attendance_rate': session_data['stats']['attendance_rate'] if 'attendance_rate' in session_data[
                        'stats'] else 0
                }

                summary['total_expected'] += session_data['stats']['total_expected']
                summary['total_present'] += session_data['stats']['total_present']

        # Calculate overall attendance rate
        if summary['total_expected'] > 0:
            summary['attendance_rate'] = round((summary['total_present'] / summary['total_expected']) * 100, 1)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'summary': summary
            })
        else:
            # Render template for non-AJAX requests
            return render_template('admin/attendance_summary.html',
                                   date=attendance_date,
                                   summary=summary)

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error retrieving attendance summary: {str(e)}'
        }), 500


# Attendance reports page
@admin_bp.route('/reports')
def reports():
    """Attendance reports page"""
    sessions = Session.query.all()
    return render_template('admin/reports.html', sessions=sessions)


# Search participant
@admin_bp.route('/search-participant', methods=['GET'])
def search_participant():
    """Search for a participant by name, email or ID"""
    query = request.args.get('q', '')

    if not query or len(query) < 3:
        return jsonify([])

    # Search for participants
    participants = Participant.query.filter(
        (Participant.name.ilike(f'%{query}%')) |
        (Participant.email.ilike(f'%{query}%')) |
        (Participant.unique_id.ilike(f'%{query}%'))
    ).limit(10).all()

    results = [{
        'id': p.id,
        'unique_id': p.unique_id,
        'name': p.name,
        'email': p.email,
        'classroom': p.classroom
    } for p in participants]

    return jsonify(results)


# Create participant
@admin_bp.route('/participant/add', methods=['GET', 'POST'])
def add_participant():
    """Add individual participant form and handler"""
    # Get all sessions for select options
    saturday_sessions = Session.query.filter_by(day='Saturday').all()
    sunday_sessions = Session.query.filter_by(day='Sunday').all()

    if request.method == 'POST':
        # Process form submission
        data = {
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'has_laptop': request.form.get('has_laptop') == 'yes',
            'saturday_session_id': request.form.get('saturday_session_id', type=int),
            'sunday_session_id': request.form.get('sunday_session_id', type=int)
        }

        from app.services.participant_service import add_individual_participant
        result = add_individual_participant(data)

        if result['success']:
            flash('Participant added successfully!', 'success')
            return redirect(url_for('admin.participant_details', unique_id=result['participant']['unique_id']))
        else:
            flash(f"Error: {result['message']}", 'danger')

    return render_template('admin/add_participant.html',
                           saturday_sessions=saturday_sessions,
                           sunday_sessions=sunday_sessions)


@admin_bp.route('/participant/<unique_id>/details')
def participant_details(unique_id):
    """View participant details"""
    participant = Participant.query.filter_by(unique_id=unique_id).first_or_404()

    # Get session info
    saturday_session = Session.query.get(participant.saturday_session_id)
    sunday_session = Session.query.get(participant.sunday_session_id)

    return render_template('admin/participant_details.html',
                           participant=participant,
                           saturday_session=saturday_session,
                           sunday_session=sunday_session)


@admin_bp.route('/admin/import', methods=['GET', 'POST'])
def import_data():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                # import_attendance_data(file)
                flash('Attendance data imported successfully!', 'success')
            except Exception as e:
                flash(f'Error importing data: {str(e)}', 'danger')
            return redirect(url_for('admin.import_data'))
    return render_template('admin/import.html')


@admin_bp.route('/reports/daily', methods=['GET'])
def daily_report():
    """Generate a daily attendance report"""
    date_str = request.args.get('date')
    session_id = request.args.get('session_id')
    classroom = request.args.get('classroom')

    try:
        # Parse date
        if date_str:
            try:
                report_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid date format. Use YYYY-MM-DD',
                    'error_code': 'invalid_date_format'
                }), 400
        else:
            # Use current date
            report_date = datetime.now().date()

        # Get day of week
        day_of_week = report_date.strftime("%A")

        # Get sessions
        if session_id:
            sessions = [Session.query.get(session_id)]
            if not sessions[0] or sessions[0].day != day_of_week:
                return jsonify({
                    'success': False,
                    'message': f'Session not found or not on {day_of_week}',
                    'error_code': 'invalid_session'
                }), 400
        else:
            sessions = Session.query.filter_by(day=day_of_week).all()

        # Initialize report data
        report = {
            'date': date_str or report_date.strftime('%Y-%m-%d'),
            'day': day_of_week,
            'sessions': {},
            'total_expected': 0,
            'total_present': 0,
            'attendance_rate': 0
        }

        # Process each session
        verifier = AttendanceVerifier()

        for session in sessions:
            session_data = verifier.get_attendance_by_session(session.id, date_str)

            if session_data['success']:
                # Filter by classroom if specified
                if classroom:
                    if classroom in session_data['classes']:
                        # Calculate totals for this classroom
                        present = len(session_data['classes'][classroom]['present'])
                        absent = len(session_data['classes'][classroom]['absent'])
                        expected = present + absent
                        attendance_rate = round((present / expected * 100), 1) if expected > 0 else 0

                        # Add to report
                        report['sessions'][session.time_slot] = {
                            'id': session.id,
                            'expected': expected,
                            'present': present,
                            'attendance_rate': attendance_rate
                        }

                        report['total_expected'] += expected
                        report['total_present'] += present
                else:
                    # Use overall stats
                    report['sessions'][session.time_slot] = {
                        'id': session.id,
                        'expected': session_data['stats']['total_expected'],
                        'present': session_data['stats']['total_present'],
                        'attendance_rate': session_data['stats']['attendance_rate'] if 'attendance_rate' in
                                                                                       session_data['stats'] else 0
                    }

                    report['total_expected'] += session_data['stats']['total_expected']
                    report['total_present'] += session_data['stats']['total_present']

        # Calculate overall attendance rate
        if report['total_expected'] > 0:
            report['attendance_rate'] = round((report['total_present'] / report['total_expected'] * 100), 1)

        return jsonify({
            'success': True,
            'report': report
        })

    except Exception as e:
        current_app.logger.error(f"Error generating daily report: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error generating report: {str(e)}',
            'error_code': 'report_error'
        }), 500


@admin_bp.route('/export/participants', methods=['GET'])
def export_participants():
    """
    Export participant data to Excel file.
    Endpoint: /admin/export/participants
    Method: GET
    Returns: Excel file download
    """
    try:
        from flask import send_file
        import io

        # Get Excel data
        excel_data, filename = export_participants_to_excel()

        # Create BytesIO object
        excel_io = io.BytesIO(excel_data)

        # Send file for download
        return send_file(
            excel_io,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        current_app.logger.error(f"Error exporting participants: {str(e)}")
        flash(f"Error exporting participants: {str(e)}", "danger")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/reassignment-requests', methods=['GET'])
def get_reassignment_requests():
    """Admin view for pending reassignment requests"""
    # Get pending requests
    result = reassignment_service.get_pending_requests()

    # For AJAX requests, return JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(result)

    # For regular requests, render template
    return render_template('admin/reassignment_requests.html',
                           requests=result.get('requests', []) if result['success'] else [],
                           error=None if result['success'] else result.get('message'))


@admin_bp.route('/process-reassignment/<int:request_id>', methods=['POST'])
def process_reassignment_request_old(request_id):
    """Process (approve/reject) a reassignment request"""
    # Get request data
    approve_value = request.form.get('approve', '')
    # Log the actual value for debugging
    current_app.logger.info(f"Processing reassignment request {request_id} with approve value: {approve_value}")

    # Convert strings to boolean properly
    approve = approve_value.lower() == 'true'
    admin_notes = request.form.get('admin_notes', '')

    # TODO: Get admin ID from session/auth system
    admin_id = 1  # Placeholder, replace with actual admin ID

    # Process the request
    result = reassignment_service.process_reassignment_request(
        request_id=request_id,
        admin_id=admin_id,
        approve=approve,
        admin_notes=admin_notes
    )

    current_app.logger.info(f"Result: {result}")

    # For AJAX requests, return JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(result)

    # For regular requests, show flash message and redirect
    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(f"Error: {result['message']}", 'danger')

    return redirect(url_for('admin.get_reassignment_requests'))
