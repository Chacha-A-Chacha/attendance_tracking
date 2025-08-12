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


# Add this to your existing app.py or create a new route file

from flask import jsonify, request, current_app
from utils.enhanced_email import email_service, email_queue, email_statuses, EmailStatus, Priority
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


@email_bp.route('/test-email')
def test_email_setup():
    """
    Simple endpoint to test email configuration.
    Usage:
    - GET /test-email - Shows current config (without password)
    - GET /test-email?send=true&to=your@email.com - Sends test email
    - GET /test-email?direct=true&to=your@email.com - Tests direct SMTP
    """

    # Get parameters
    send_test = request.args.get('send', '').lower() == 'true'
    direct_test = request.args.get('direct', '').lower() == 'true'
    recipient = request.args.get('to', '')

    # Show current configuration
    config_info = {
        'email_service_running': email_service.running if email_service else False,
        'worker_thread_alive': email_service.worker_thread.is_alive() if email_service and email_service.worker_thread else False,
        'queue_size': email_service.get_queue_stats()['queue_size'] if email_service else 0,
        'config': {
            'MAIL_SERVER': current_app.config.get('MAIL_SERVER'),
            'MAIL_PORT': current_app.config.get('MAIL_PORT'),
            'MAIL_USE_TLS': current_app.config.get('MAIL_USE_TLS'),
            'MAIL_USE_SSL': current_app.config.get('MAIL_USE_SSL'),
            'MAIL_USERNAME': current_app.config.get('MAIL_USERNAME'),
            'MAIL_DEFAULT_SENDER': current_app.config.get('MAIL_DEFAULT_SENDER'),
            'MAIL_PASSWORD_SET': bool(current_app.config.get('MAIL_PASSWORD'))
        }
    }

    # If not sending test, just return config
    if not send_test and not direct_test:
        return jsonify({
            'status': 'success',
            'message': 'Email configuration display',
            'config': config_info,
            'usage': {
                'send_via_service': '/test-email?send=true&to=your@email.com',
                'send_direct_smtp': '/test-email?direct=true&to=your@email.com'
            }
        })

    # Validate recipient email
    if not recipient:
        return jsonify({
            'status': 'error',
            'message': 'Recipient email required. Add ?to=your@email.com'
        }), 400

    if '@' not in recipient:
        return jsonify({
            'status': 'error',
            'message': 'Invalid email format'
        }), 400

    try:
        if direct_test:
            # Test direct SMTP connection
            result = test_direct_smtp(recipient)
            return jsonify({
                'status': 'success' if result['success'] else 'error',
                'message': result['message'],
                'method': 'direct_smtp',
                'config': config_info
            })

        else:
            # Test via email service
            result = test_via_service(recipient)
            return jsonify({
                'status': 'success' if result['success'] else 'error',
                'message': result['message'],
                'task_id': result.get('task_id'),
                'method': 'email_service',
                'config': config_info
            })

    except Exception as e:
        current_app.logger.error(f"Email test failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Email test failed: {str(e)}',
            'config': config_info
        }), 500


def test_direct_smtp(recipient):
    """Test direct SMTP connection without using the email service."""
    try:
        # Validate configuration
        required_config = ['MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD']
        missing_config = [key for key in required_config if not current_app.config.get(key)]

        if missing_config:
            return {
                'success': False,
                'message': f'Missing configuration: {", ".join(missing_config)}'
            }

        # Create test message
        msg = MIMEMultipart()
        msg['Subject'] = '[DIRECT SMTP TEST] Email Configuration Test'
        msg['From'] = current_app.config['MAIL_DEFAULT_SENDER']
        msg['To'] = recipient

        # Create email body
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body = f"""
This is a direct SMTP test email from the Programming Course system.

Test Details:
- Timestamp: {timestamp}
- Server: {current_app.config['MAIL_SERVER']}:{current_app.config['MAIL_PORT']}
- SSL: {current_app.config['MAIL_USE_SSL']}
- TLS: {current_app.config['MAIL_USE_TLS']}
- Username: {current_app.config['MAIL_USERNAME']}

If you received this email, your SMTP configuration is working correctly!
        """

        msg.attach(MIMEText(body, 'plain'))

        # Connect and send
        if current_app.config['MAIL_USE_SSL']:
            server = smtplib.SMTP_SSL(
                current_app.config['MAIL_SERVER'],
                current_app.config['MAIL_PORT']
            )
        else:
            server = smtplib.SMTP(
                current_app.config['MAIL_SERVER'],
                current_app.config['MAIL_PORT']
            )
            if current_app.config['MAIL_USE_TLS']:
                server.starttls()

        server.login(
            current_app.config['MAIL_USERNAME'],
            current_app.config['MAIL_PASSWORD']
        )

        server.send_message(msg)
        server.quit()

        return {
            'success': True,
            'message': f'Test email sent successfully to {recipient} via direct SMTP'
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Direct SMTP test failed: {str(e)}'
        }


def test_via_service(recipient):
    """Test email via the enhanced email service."""
    try:
        # Check if service is running
        if not email_service or not email_service.running:
            return {
                'success': False,
                'message': 'Email service is not running'
            }

        # Create task ID
        task_id = f"test_{int(datetime.now().timestamp())}"

        # Create email status
        status = EmailStatus(
            recipient=recipient,
            subject='[SERVICE TEST] Email Service Test',
            task_id=task_id,
            group_id='system_test'
        )
        status.priority = Priority.HIGH
        email_statuses[task_id] = status

        # Create email body
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html_body = f"""
        <html>
        <body>
            <h2>Email Service Test</h2>
            <p><strong>This is a test email from the Programming Course enhanced email service.</strong></p>

            <h3>Test Details:</h3>
            <ul>
                <li>Task ID: {task_id}</li>
                <li>Timestamp: {timestamp}</li>
                <li>Priority: High</li>
                <li>Service: Enhanced Email Service</li>
                <li>Queue Status: Active</li>
            </ul>

            <p>If you received this email, your email service is working correctly!</p>
        </body>
        </html>
        """

        text_body = f"""
Email Service Test

This is a test email from the Programming Course enhanced email service.

Test Details:
- Task ID: {task_id}
- Timestamp: {timestamp}
- Priority: High
- Service: Enhanced Email Service
- Queue Status: Active

If you received this email, your email service is working correctly!
        """

        # Create email task
        task = {
            'recipient': recipient,
            'subject': '[SERVICE TEST] Email Service Test',
            'html_body': html_body,
            'text_body': text_body,
            'task_id': task_id,
            'group_id': 'system_test'
        }

        # Add to queue
        email_queue.put(task, Priority.HIGH)

        return {
            'success': True,
            'message': f'Test email queued successfully for {recipient}',
            'task_id': task_id
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Email service test failed: {str(e)}'
        }


# Optional: Add task status check endpoint
@email_bp.route('/test-email/status/<task_id>')
def check_email_task_status(task_id):
    """Check the status of a specific email task."""
    try:
        if task_id in email_statuses:
            status = email_statuses[task_id]
            return jsonify({
                'status': 'success',
                'task_status': {
                    'task_id': task_id,
                    'recipient': status.recipient,
                    'subject': status.subject,
                    'status': status.status,
                    'attempts': status.attempts,
                    'timestamp': status.timestamp.isoformat() if status.timestamp else None,
                    'sent_time': status.sent_time.isoformat() if status.sent_time else None,
                    'error': status.error
                }
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Task not found'
            }), 404

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
