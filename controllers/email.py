# controllers/email_admin.py
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from utils.enhanced_email import EnhancedEmailService, Priority, EmailStatus
from app import db, email_service
from models import Participant, Session
from sqlalchemy import or_
import uuid
from datetime import datetime
import os

email_bp = Blueprint('email_admin', __name__, url_prefix='/email-admin')


@email_bp.route('/')
def index():
    """Email administration dashboard"""
    stats = email_service.get_queue_stats()

    # Get available classrooms
    classrooms = db.session.query(Participant.classroom).distinct().all()
    classrooms = [c[0] for c in classrooms]

    # Get available sessions
    sessions = Session.query.all()

    return render_template('email_admin/index.html',
                           stats=stats,
                           classrooms=classrooms,
                           sessions=sessions)


@email_bp.route('/queue-stats')
def queue_stats():
    """Get current queue statistics as JSON for AJAX updates"""
    stats = email_service.get_queue_stats()
    return jsonify(stats)


@email_bp.route('/email-status/<task_id>')
def email_status(task_id):
    """Get status of a specific email"""
    status = email_service.get_email_status(task_id)
    if status:
        return jsonify(status)
    return jsonify({'error': 'Email task not found'}), 404


@email_bp.route('/batch-status/<batch_id>')
def batch_status(batch_id):
    """Get status of all emails in a batch"""
    status = email_service.get_batch_status(batch_id)
    if status:
        return jsonify(status)
    return jsonify({'error': 'Batch not found'}), 404


@email_bp.route('/batch-details/<batch_id>')
def batch_details(batch_id):
    """Show details for a specific batch"""
    batch_status = email_service.get_batch_status(batch_id)

    if not batch_status:
        flash('Batch not found', 'error')
        return redirect(url_for('email_admin.index'))

    return render_template('email_admin/batch_details.html', batch=batch_status)


@email_bp.route('/send-qr-emails', methods=['POST'])
def send_qr_emails():
    """Send QR code emails to a group of participants"""
    form_data = request.form

    # Get target group parameters
    classroom = form_data.get('classroom')
    session_day = form_data.get('session_day')
    session_time = form_data.get('session_time')
    participant_ids = form_data.getlist('participant_ids')

    # Set priority
    priority_str = form_data.get('priority', 'normal')
    if priority_str == 'high':
        priority = Priority.HIGH
    elif priority_str == 'low':
        priority = Priority.LOW
    else:
        priority = Priority.NORMAL

    # Create batch ID
    batch_id = f"qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Find participants based on criteria
    query = Participant.query

    if classroom:
        query = query.filter(Participant.classroom == classroom)

    if session_day and session_time:
        session = Session.query.filter_by(day=session_day, time_slot=session_time).first()
        if session:
            if session_day.lower() == 'saturday':
                query = query.filter(Participant.saturday_session_id == session.id)
            else:
                query = query.filter(Participant.sunday_session_id == session.id)

    if participant_ids:
        # If specific IDs provided, use those instead
        query = Participant.query.filter(Participant.id.in_(participant_ids))

    participants = query.all()

    if not participants:
        flash('No participants found matching the selected criteria', 'warning')
        return redirect(url_for('email_admin.index'))

    # Send emails
    task_ids = []
    for participant in participants:
        if participant.email and participant.qrcode_path and os.path.exists(participant.qrcode_path):
            task_id = email_service.send_qr_code(
                recipient=participant.email,
                participant=participant,
                priority=priority,
                batch_id=batch_id
            )
            task_ids.append(task_id)

    flash(f'Queued {len(task_ids)} QR code emails for sending', 'success')
    return redirect(url_for('email_admin.batch_details', batch_id=batch_id))


@email_bp.route('/send-class-notification', methods=['POST'])
def send_class_notification():
    """Send a notification to all participants in a class"""
    form_data = request.form

    # Get parameters
    classroom = form_data.get('classroom')
    subject = form_data.get('subject')
    template = form_data.get('template')
    custom_message = form_data.get('custom_message', '')

    # Validate inputs
    if not classroom or not subject or not template:
        flash('Missing required fields', 'error')
        return redirect(url_for('email_admin.index'))

    # Set priority
    priority_str = form_data.get('priority', 'normal')
    if priority_str == 'high':
        priority = Priority.HIGH
    elif priority_str == 'low':
        priority = Priority.LOW
    else:
        priority = Priority.NORMAL

    try:
        # Create template context
        template_context = {
            'custom_message': custom_message
        }

        # Send notifications
        result = email_service.send_class_notification(
            classroom=classroom,
            subject=subject,
            template=template,
            template_context=template_context,
            priority=priority
        )

        flash(f'Queued {result["participant_count"]} notifications for sending', 'success')
        return redirect(url_for('email_admin.batch_details', batch_id=result['batch_id']))

    except Exception as e:
        flash(f'Error sending notifications: {str(e)}', 'error')
        return redirect(url_for('email_admin.index'))


@email_bp.route('/send-session-notification', methods=['POST'])
def send_session_notification():
    """Send a notification to all participants in a session"""
    form_data = request.form

    # Get parameters
    session_day = form_data.get('session_day')
    session_time = form_data.get('session_time')
    subject = form_data.get('subject')
    template = form_data.get('template')
    custom_message = form_data.get('custom_message', '')

    # Validate inputs
    if not session_day or not session_time or not subject or not template:
        flash('Missing required fields', 'error')
        return redirect(url_for('email_admin.index'))

    # Set priority
    priority_str = form_data.get('priority', 'normal')
    if priority_str == 'high':
        priority = Priority.HIGH
    elif priority_str == 'low':
        priority = Priority.LOW
    else:
        priority = Priority.NORMAL

    try:
        # Create template context
        template_context = {
            'custom_message': custom_message
        }

        # Send notifications
        result = email_service.send_session_notification(
            day=session_day,
            time_slot=session_time,
            subject=subject,
            template=template,
            template_context=template_context,
            priority=priority
        )

        flash(f'Queued {result["participant_count"]} notifications for sending', 'success')
        return redirect(url_for('email_admin.batch_details', batch_id=result['batch_id']))

    except Exception as e:
        flash(f'Error sending notifications: {str(e)}', 'error')
        return redirect(url_for('email_admin.index'))


@email_bp.route('/cancel-email/<task_id>', methods=['POST'])
def cancel_email(task_id):
    """Cancel a queued email"""
    success = email_service.cancel_email(task_id)

    if success:
        return jsonify({'success': True, 'message': 'Email cancelled'})
    else:
        return jsonify(
            {'success': False, 'message': 'Unable to cancel email, it may already be sent or in process'}), 400


@email_bp.route('/retry-email/<task_id>', methods=['POST'])
def retry_email(task_id):
    """Retry a failed email"""
    success = email_service.retry_failed_email(task_id)

    if success:
        return jsonify({'success': True, 'message': 'Email queued for retry'})
    else:
        return jsonify({'success': False, 'message': 'Unable to retry email, check status'}), 400


@email_bp.route('/cancel-batch/<batch_id>', methods=['POST'])
def cancel_batch(batch_id):
    """Cancel all pending emails in a batch"""
    batch_status = email_service.get_batch_status(batch_id)

    if not batch_status:
        return jsonify({'success': False, 'message': 'Batch not found'}), 404

    cancelled = 0
    for task_id in batch_status['tasks']:
        if email_service.cancel_email(task_id):
            cancelled += 1

    return jsonify({
        'success': True,
        'message': f'Cancelled {cancelled} emails in batch',
        'cancelled_count': cancelled
    })


@email_bp.route('/templates')
def list_templates():
    """List available email templates"""
    template_path = os.path.join(current_app.root_path, 'templates', 'emails')
    templates = []

    if os.path.exists(template_path):
        for file in os.listdir(template_path):
            if file.endswith('.html'):
                template_name = os.path.splitext(file)[0]
                if template_name not in templates:
                    templates.append(template_name)

    return render_template('email_admin/templates.html', templates=templates)


@email_bp.route('/clean-old-status', methods=['POST'])
def clean_old_status():
    """Clean up old email statuses"""
    days = int(request.form.get('days', 30))
    result = email_service.clean_old_statuses(days)

    flash(f'Removed {result["removed"]} old email status entries', 'success')
    return redirect(url_for('email_admin.index'))
