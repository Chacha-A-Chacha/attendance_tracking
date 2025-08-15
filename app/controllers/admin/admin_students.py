# controllers/admin_students.py
"""
Admin student/participant management routes.
Handles participant overview, session assignments, attendance tracking, and reassignment requests.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, desc, case, exists
from sqlalchemy.orm import joinedload, selectinload
from datetime import datetime, timedelta

from app.models.participant import Participant
from app.models.session import Session
from app.models.attendance import Attendance
from app.models.session_reassignment import SessionReassignmentRequest, ReassignmentStatus
from app.models.user import User, Permission
from app.services.session_classroom_service import SessionClassroomService
from app.utils.auth import permission_required, staff_required
from app.extensions import db

# Use the main admin blueprint as requested
admin_bp = Blueprint('admin_students', __name__, url_prefix='/admin/students')


@admin_bp.route('/participants')
@login_required
@staff_required
def all_participants():
    """All participants dashboard with comprehensive filtering and search."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '', type=str)
    classroom_filter = request.args.get('classroom', '', type=str)
    has_laptop_filter = request.args.get('has_laptop', '', type=str)
    has_user_filter = request.args.get('has_user', '', type=str)
    graduation_status_filter = request.args.get('graduation_status', '', type=str)

    try:
        # Base query with optimized loading
        query = (
            db.session.query(Participant)
            .options(
                joinedload(Participant.saturday_session),
                joinedload(Participant.sunday_session),
                joinedload(Participant.user)
            )
        )

        # Apply search filter
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Participant.unique_id.ilike(search_pattern),
                    Participant.first_name.ilike(search_pattern),
                    Participant.surname.ilike(search_pattern),
                    Participant.email.ilike(search_pattern),
                    Participant.phone.ilike(search_pattern)
                )
            )

        # Apply filters
        if classroom_filter:
            query = query.filter(Participant.classroom == classroom_filter)

        if has_laptop_filter:
            if has_laptop_filter == 'yes':
                query = query.filter(Participant.has_laptop == True)
            elif has_laptop_filter == 'no':
                query = query.filter(Participant.has_laptop == False)

        if has_user_filter:
            if has_user_filter == 'yes':
                query = query.filter(exists().where(User.participant_id == Participant.id))
            elif has_user_filter == 'no':
                query = query.filter(~exists().where(User.participant_id == Participant.id))

        if graduation_status_filter:
            query = query.filter(Participant.graduation_status == graduation_status_filter)

        # Order by registration date (newest first)
        query = query.order_by(Participant.registration_timestamp.desc())

        # Paginate results
        participants = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        # Get statistics
        stats = {
            'total_participants': db.session.query(func.count(Participant.id)).scalar(),
            'by_classroom': dict(
                db.session.query(
                    Participant.classroom,
                    func.count(Participant.id)
                ).group_by(Participant.classroom).all()
            ),
            'with_laptops': db.session.query(func.count(Participant.id))
            .filter(Participant.has_laptop == True).scalar(),
            'with_user_accounts': db.session.query(func.count(Participant.id))
            .filter(exists().where(User.participant_id == Participant.id)).scalar(),
            'graduated': db.session.query(func.count(Participant.id))
            .filter(Participant.graduation_status == 'graduated').scalar(),
            'eligible_for_graduation': db.session.query(func.count(Participant.id))
            .filter(Participant.graduation_status == 'eligible').scalar()
        }

        # Get classroom utilization
        classroom_utilization = SessionClassroomService.get_classroom_utilization()

        return render_template(
            'admin/students/all_participants.html',
            participants=participants,
            stats=stats,
            classroom_utilization=classroom_utilization,
            search=search,
            classroom_filter=classroom_filter,
            has_laptop_filter=has_laptop_filter,
            has_user_filter=has_user_filter,
            graduation_status_filter=graduation_status_filter
        )

    except Exception as e:
        flash('Error loading participants.', 'error')
        current_app.logger.error(f"Participants listing error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/session-assignments')
@login_required
@staff_required
def session_assignments():
    """Session assignment management dashboard."""
    classroom_filter = request.args.get('classroom', '', type=str)
    day_filter = request.args.get('day', '', type=str)
    session_filter = request.args.get('session', '', type=str)

    try:
        # Get comprehensive session report
        session_report = SessionClassroomService.get_comprehensive_session_report()

        # Get capacity warnings
        capacity_warnings = SessionClassroomService.get_capacity_warnings()

        # Get session assignment data for display
        assignment_data = {}

        for day in ['Saturday', 'Sunday']:
            sessions = SessionClassroomService.get_sessions_by_day(day)
            day_data = []

            for session in sessions:
                # Get participants for each classroom
                laptop_classroom = current_app.config.get('LAPTOP_CLASSROOM', '205')
                no_laptop_classroom = current_app.config.get('NO_LAPTOP_CLASSROOM', '203')

                # Get participants assigned to this session
                if day == 'Saturday':
                    participants = (
                        db.session.query(Participant)
                        .options(joinedload(Participant.user))
                        .filter(Participant.saturday_session_id == session.id)
                        .order_by(Participant.classroom, Participant.surname, Participant.first_name)
                        .all()
                    )
                else:
                    participants = (
                        db.session.query(Participant)
                        .options(joinedload(Participant.user))
                        .filter(Participant.sunday_session_id == session.id)
                        .order_by(Participant.classroom, Participant.surname, Participant.first_name)
                        .all()
                    )

                # Group by classroom
                laptop_participants = [p for p in participants if p.classroom == laptop_classroom]
                no_laptop_participants = [p for p in participants if p.classroom == no_laptop_classroom]

                day_data.append({
                    'session': session,
                    'laptop_participants': laptop_participants,
                    'no_laptop_participants': no_laptop_participants,
                    'total_count': len(participants),
                    'laptop_count': len(laptop_participants),
                    'no_laptop_count': len(no_laptop_participants)
                })

            assignment_data[day.lower()] = day_data

        return render_template(
            'admin/students/session_assignments.html',
            assignment_data=assignment_data,
            session_report=session_report,
            capacity_warnings=capacity_warnings,
            classroom_filter=classroom_filter,
            day_filter=day_filter,
            session_filter=session_filter
        )

    except Exception as e:
        flash('Error loading session assignments.', 'error')
        current_app.logger.error(f"Session assignments error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/attendance-records')
@login_required
@staff_required
def attendance_records():
    """Attendance tracking and analytics dashboard."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)
    participant_search = request.args.get('participant_search', '', type=str)
    classroom_filter = request.args.get('classroom', '', type=str)
    session_filter = request.args.get('session', '', type=str)
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)
    status_filter = request.args.get('status', '', type=str)

    try:
        # Base query for attendance records with optimized loading
        query = (
            db.session.query(Attendance)
            .options(
                joinedload(Attendance.participant),
                joinedload(Attendance.session)
            )
        )

        # Apply filters
        if participant_search:
            search_pattern = f"%{participant_search}%"
            query = query.join(Attendance.participant).filter(
                or_(
                    Participant.unique_id.ilike(search_pattern),
                    Participant.first_name.ilike(search_pattern),
                    Participant.surname.ilike(search_pattern)
                )
            )

        if classroom_filter:
            query = query.join(Attendance.participant).filter(
                Participant.classroom == classroom_filter
            )

        if session_filter:
            query = query.filter(Attendance.session_id == session_filter)

        if status_filter:
            query = query.filter(Attendance.status == status_filter)

        # Date range filter
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(Attendance.timestamp >= from_date)
            except ValueError:
                flash('Invalid from date format.', 'warning')

        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Attendance.timestamp <= to_date)
            except ValueError:
                flash('Invalid to date format.', 'warning')

        # Order by timestamp (newest first)
        query = query.order_by(Attendance.timestamp.desc())

        # Paginate results
        attendance_records = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        # Get attendance statistics
        total_records = db.session.query(func.count(Attendance.id)).scalar()

        # Status breakdown
        status_stats = dict(
            db.session.query(
                Attendance.status,
                func.count(Attendance.id)
            ).group_by(Attendance.status).all()
        )

        # Correct vs incorrect session attendance
        session_accuracy = dict(
            db.session.query(
                Attendance.is_correct_session,
                func.count(Attendance.id)
            ).group_by(Attendance.is_correct_session).all()
        )

        # Recent attendance trends (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        daily_attendance = (
            db.session.query(
                func.date(Attendance.timestamp).label('date'),
                func.count(Attendance.id).label('count')
            )
            .filter(Attendance.timestamp >= week_ago)
            .group_by(func.date(Attendance.timestamp))
            .order_by('date')
            .all()
        )

        # Participants with attendance issues
        problem_participants = (
            db.session.query(Participant)
            .filter(Participant.consecutive_missed_sessions >= 2)
            .order_by(Participant.consecutive_missed_sessions.desc())
            .limit(10)
            .all()
        )

        stats = {
            'total_records': total_records,
            'status_breakdown': status_stats,
            'session_accuracy': session_accuracy,
            'daily_trends': [
                {'date': day.date.strftime('%Y-%m-%d'), 'count': day.count}
                for day in daily_attendance
            ],
            'problem_participants_count': len(problem_participants)
        }

        # Get available sessions for filter
        available_sessions = db.session.query(Session).order_by(Session.day, Session.time_slot).all()

        return render_template(
            'admin/students/attendance_records.html',
            attendance_records=attendance_records,
            stats=stats,
            problem_participants=problem_participants,
            available_sessions=available_sessions,
            participant_search=participant_search,
            classroom_filter=classroom_filter,
            session_filter=session_filter,
            date_from=date_from,
            date_to=date_to,
            status_filter=status_filter
        )

    except Exception as e:
        flash('Error loading attendance records.', 'error')
        current_app.logger.error(f"Attendance records error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/reassignment-requests')
@login_required
@staff_required
def reassignment_requests():
    """Session reassignment requests management."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status', 'pending', type=str)
    day_filter = request.args.get('day', '', type=str)
    priority_filter = request.args.get('priority', '', type=str)

    try:
        # Get pending requests using the service
        if status_filter == 'pending':
            requests = SessionClassroomService.get_pending_reassignment_requests(
                limit=per_page,
                offset=(page - 1) * per_page
            )
            total_requests = len(requests)  # For pagination calculation
        else:
            # Get all requests with status filter
            query = (
                db.session.query(SessionReassignmentRequest)
                .options(
                    joinedload(SessionReassignmentRequest.participant),
                    joinedload(SessionReassignmentRequest.current_session),
                    joinedload(SessionReassignmentRequest.requested_session)
                )
                .filter(SessionReassignmentRequest.status == status_filter)
            )

            if day_filter:
                query = query.filter(SessionReassignmentRequest.day_type == day_filter)

            if priority_filter:
                query = query.filter(SessionReassignmentRequest.priority == priority_filter)

            query = query.order_by(
                SessionReassignmentRequest.priority.desc(),
                SessionReassignmentRequest.created_at.asc()
            )

            total_requests = query.count()
            requests_db = query.offset((page - 1) * per_page).limit(per_page).all()

            # Convert to format similar to service method
            requests = []
            for req in requests_db:
                requests.append({
                    'id': req.id,
                    'participant': {
                        'id': req.participant.id,
                        'unique_id': req.participant.unique_id,
                        'full_name': req.participant.full_name,
                        'email': req.participant.email,
                        'classroom': req.participant.classroom,
                        'reassignments_count': req.participant.reassignments_count
                    },
                    'day_type': req.day_type,
                    'current_session': req.current_session.time_slot,
                    'requested_session': req.requested_session.time_slot,
                    'reason': req.reason,
                    'priority': req.priority,
                    'status': req.status,
                    'created_at': req.created_at.isoformat(),
                    'reviewed_at': req.reviewed_at.isoformat() if req.reviewed_at else None,
                    'admin_notes': req.admin_notes,
                    'days_pending': (datetime.now() - req.created_at).days
                })

        # Get reassignment statistics
        reassignment_stats = {
            'pending': db.session.query(func.count(SessionReassignmentRequest.id))
            .filter(SessionReassignmentRequest.status == ReassignmentStatus.PENDING).scalar(),
            'approved': db.session.query(func.count(SessionReassignmentRequest.id))
            .filter(SessionReassignmentRequest.status == ReassignmentStatus.APPROVED).scalar(),
            'rejected': db.session.query(func.count(SessionReassignmentRequest.id))
            .filter(SessionReassignmentRequest.status == ReassignmentStatus.REJECTED).scalar(),
            'this_week': db.session.query(func.count(SessionReassignmentRequest.id))
            .filter(SessionReassignmentRequest.created_at >= datetime.now() - timedelta(days=7)).scalar()
        }

        # Get participants with multiple reassignments
        frequent_requesters = (
            db.session.query(Participant)
            .filter(Participant.reassignments_count >= 2)
            .order_by(Participant.reassignments_count.desc())
            .limit(10)
            .all()
        )

        return render_template(
            'admin/students/reassignment_requests.html',
            requests=requests,
            stats=reassignment_stats,
            frequent_requesters=frequent_requesters,
            total_requests=total_requests,
            status_filter=status_filter,
            day_filter=day_filter,
            priority_filter=priority_filter,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        flash('Error loading reassignment requests.', 'error')
        current_app.logger.error(f"Reassignment requests error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/participant/<participant_id>')
@login_required
@staff_required
def participant_detail(participant_id):
    """Detailed view of a specific participant."""
    try:
        participant = (
            db.session.query(Participant)
            .options(
                joinedload(Participant.saturday_session),
                joinedload(Participant.sunday_session),
                joinedload(Participant.user),
                selectinload(Participant.attendances).joinedload(Attendance.session),
                selectinload(Participant.reassignment_requests)
                .joinedload(SessionReassignmentRequest.current_session),
                selectinload(Participant.reassignment_requests)
                .joinedload(SessionReassignmentRequest.requested_session)
            )
            .filter_by(id=participant_id)
            .first_or_404()
        )

        # Get attendance summary
        attendance_summary = participant.get_attendance_summary()

        # Get recent attendance (last 20 records)
        recent_attendance = participant.get_recent_attendances(limit=20)

        # Get reassignment history
        reassignment_history = SessionClassroomService.get_participant_reassignment_history(
            participant_id, limit=20
        )

        # Get available sessions for potential reassignment
        saturday_sessions = SessionClassroomService.get_available_sessions_with_capacity(
            'Saturday', participant.has_laptop, participant.saturday_session_id
        )
        sunday_sessions = SessionClassroomService.get_available_sessions_with_capacity(
            'Sunday', participant.has_laptop, participant.sunday_session_id
        )

        return render_template(
            'admin/students/participant_detail.html',
            participant=participant,
            attendance_summary=attendance_summary,
            recent_attendance=recent_attendance,
            reassignment_history=reassignment_history,
            saturday_sessions=saturday_sessions,
            sunday_sessions=sunday_sessions
        )

    except Exception as e:
        flash('Error loading participant details.', 'error')
        current_app.logger.error(f"Participant detail error: {str(e)}")
        return redirect(url_for('admin_students.all_participants'))


@admin_bp.route('/reassignment-request/<request_id>/process', methods=['GET', 'POST'])
@login_required
@staff_required
def process_reassignment_request(request_id):
    """Process (approve or reject) a reassignment request."""
    try:
        # Get the request with related data
        reassignment_request = (
            db.session.query(SessionReassignmentRequest)
            .options(
                joinedload(SessionReassignmentRequest.participant),
                joinedload(SessionReassignmentRequest.current_session),
                joinedload(SessionReassignmentRequest.requested_session)
            )
            .filter_by(id=request_id)
            .first_or_404()
        )

        if reassignment_request.status != ReassignmentStatus.PENDING:
            flash('This request has already been processed.', 'info')
            return redirect(url_for('admin_students.reassignment_requests'))

        if request.method == 'POST':
            action = request.form.get('action')
            admin_notes = request.form.get('admin_notes', '').strip()

            if action not in ['approve', 'reject']:
                flash('Invalid action.', 'error')
                return redirect(url_for('admin_students.reassignment_requests'))

            approve = action == 'approve'

            # Process the request using the service
            result = SessionClassroomService.process_reassignment_request(
                request_id=request_id,
                admin_id=current_user.id,
                approve=approve,
                admin_notes=admin_notes
            )

            if result['success']:
                flash(result['message'], 'success')
            else:
                flash(result['message'], 'error')

            return redirect(url_for('admin_students.reassignment_requests'))

        # Check current capacity for the requested session
        participant = reassignment_request.participant
        classroom = participant.classroom
        current_count = SessionClassroomService.get_session_participant_count(
            reassignment_request.requested_session_id,
            classroom,
            reassignment_request.day_type
        )
        capacity = SessionClassroomService.get_classroom_capacity(classroom)

        capacity_info = {
            'current': current_count,
            'capacity': capacity,
            'available': capacity - current_count,
            'at_capacity': current_count >= capacity
        }

        return render_template(
            'admin/students/process_reassignment.html',
            request=reassignment_request,
            capacity_info=capacity_info
        )

    except Exception as e:
        flash('Error processing reassignment request.', 'error')
        current_app.logger.error(f"Process reassignment error: {str(e)}")
        return redirect(url_for('admin_students.reassignment_requests'))


# AJAX Endpoints for Student Management

@admin_bp.route('/search-participants', methods=['POST'])
@login_required
@staff_required
def search_participants():
    """AJAX endpoint for participant search."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    search_term = data.get('search', '').strip()
    limit = data.get('limit', 15)

    if not search_term:
        return jsonify({'participants': []})

    try:
        search_pattern = f"%{search_term}%"
        participants = (
            db.session.query(Participant)
            .options(
                joinedload(Participant.saturday_session),
                joinedload(Participant.sunday_session),
                joinedload(Participant.user)
            )
            .filter(
                or_(
                    Participant.unique_id.ilike(search_pattern),
                    Participant.first_name.ilike(search_pattern),
                    Participant.surname.ilike(search_pattern),
                    Participant.email.ilike(search_pattern)
                )
            )
            .limit(limit)
            .all()
        )

        participants_data = []
        for participant in participants:
            participants_data.append({
                'id': participant.id,
                'unique_id': participant.unique_id,
                'full_name': participant.full_name,
                'email': participant.email,
                'classroom': participant.classroom,
                'has_laptop': participant.has_laptop,
                'has_user_account': participant.has_user_account(),
                'saturday_session': participant.saturday_session.time_slot if participant.saturday_session else None,
                'sunday_session': participant.sunday_session.time_slot if participant.sunday_session else None,
                'graduation_status': participant.graduation_status,
                'consecutive_missed_sessions': participant.consecutive_missed_sessions
            })

        return jsonify({'participants': participants_data})

    except Exception as e:
        current_app.logger.error(f"Participant search error: {str(e)}")
        return jsonify({'error': 'Search failed'}), 500


@admin_bp.route('/quick-reassign-session', methods=['POST'])
@login_required
@staff_required
def quick_reassign_session():
    """AJAX endpoint for quick session reassignment by admin."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    participant_id = data.get('participant_id')
    day_type = data.get('day_type')
    new_session_id = data.get('new_session_id')
    reason = data.get('reason', 'Admin reassignment')

    if not all([participant_id, day_type, new_session_id]):
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        participant = db.session.query(Participant).get(participant_id)
        if not participant:
            return jsonify({'error': 'Participant not found'}), 404

        # Check capacity
        classroom = participant.classroom
        current_count = SessionClassroomService.get_session_participant_count(
            new_session_id, classroom, day_type
        )
        capacity = SessionClassroomService.get_classroom_capacity(classroom)

        if current_count >= capacity:
            return jsonify({'error': 'Target session is at capacity'}), 400

        # Update participant session assignment
        if day_type == 'Saturday':
            participant.saturday_session_id = new_session_id
        else:
            participant.sunday_session_id = new_session_id

        # Increment reassignment count
        participant.reassignments_count += 1

        db.session.commit()

        # Get updated session info
        new_session = db.session.query(Session).get(new_session_id)

        return jsonify({
            'success': True,
            'message': f'Participant reassigned to {day_type} session {new_session.time_slot}',
            'new_session': new_session.time_slot
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Quick reassignment error: {str(e)}")
        return jsonify({'error': 'Reassignment failed'}), 500


@admin_bp.route('/bulk-session-action', methods=['POST'])
@login_required
@staff_required
def bulk_session_action():
    """Handle bulk actions on participant sessions."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    action = data.get('action')
    participant_ids = data.get('participant_ids', [])
    session_id = data.get('session_id')
    day_type = data.get('day_type')

    if not action or not participant_ids:
        return jsonify({'error': 'Action and participant IDs are required'}), 400

    try:
        results = {'success': 0, 'failed': 0, 'messages': []}

        for participant_id in participant_ids:
            try:
                participant = db.session.query(Participant).get(participant_id)
                if not participant:
                    results['failed'] += 1
                    results['messages'].append(f'Participant {participant_id} not found')
                    continue

                if action == 'reassign_session' and session_id and day_type:
                    # Check capacity
                    current_count = SessionClassroomService.get_session_participant_count(
                        session_id, participant.classroom, day_type
                    )
                    capacity = SessionClassroomService.get_classroom_capacity(participant.classroom)

                    if current_count >= capacity:
                        results['failed'] += 1
                        results['messages'].append(f'Session at capacity for {participant.unique_id}')
                        continue

                    # Reassign
                    if day_type == 'Saturday':
                        participant.saturday_session_id = session_id
                    else:
                        participant.sunday_session_id = session_id

                    participant.reassignments_count += 1
                    results['success'] += 1

                elif action == 'reset_missed_sessions':
                    participant.consecutive_missed_sessions = 0
                    if participant.user:
                        participant.user.is_active = True
                    results['success'] += 1

                else:
                    results['failed'] += 1
                    results['messages'].append(f'Unknown action or missing parameters')

            except Exception as e:
                results['failed'] += 1
                results['messages'].append(f'Failed for {participant_id}: {str(e)}')

        db.session.commit()

        return jsonify({
            'success': True,
            'results': results,
            'message': f'Bulk action completed: {results["success"]} succeeded, {results["failed"]} failed'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bulk session action error: {str(e)}")
        return jsonify({'success': False, 'message': 'Bulk action failed'}), 500


@admin_bp.route('/capacity-check/<session_id>/<classroom>')
@login_required
@staff_required
def check_session_capacity(session_id, classroom):
    """AJAX endpoint to check session capacity."""
    try:
        # Get current count for Saturday
        saturday_count = SessionClassroomService.get_session_participant_count(
            session_id, classroom, 'Saturday'
        )

        # Get current count for Sunday
        sunday_count = SessionClassroomService.get_session_participant_count(
            session_id, classroom, 'Sunday'
        )

        capacity = SessionClassroomService.get_classroom_capacity(classroom)

        return jsonify({
            'saturday': {
                'current': saturday_count,
                'capacity': capacity,
                'available': capacity - saturday_count,
                'at_capacity': saturday_count >= capacity
            },
            'sunday': {
                'current': sunday_count,
                'capacity': capacity,
                'available': capacity - sunday_count,
                'at_capacity': sunday_count >= capacity
            }
        })

    except Exception as e:
        current_app.logger.error(f"Capacity check error: {str(e)}")
        return jsonify({'error': 'Failed to check capacity'}), 500
    