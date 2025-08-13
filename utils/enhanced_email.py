# utils/enhanced_email.py
"""
Enhanced Email Service with proper Flask context management.
This version fixes the application context issues identified in the audit.
"""

import itertools
import mimetypes
import os
import smtplib
import json
import random
import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from flask import current_app, render_template
from datetime import datetime, timedelta
import threading
import queue
import time
from sqlalchemy import or_


# Priority constants
class Priority:
    HIGH = 0
    NORMAL = 1
    LOW = 2


class EmailStatus:
    QUEUED = 'queued'
    SENDING = 'sending'
    SENT = 'sent'
    FAILED = 'failed'
    CANCELLED = 'cancelled'

    def __init__(self, recipient, subject, task_id=None, group_id=None, batch_id=None):
        self.recipient = recipient
        self.subject = subject
        self.task_id = task_id or f"email_{int(datetime.now().timestamp())}_{recipient}"
        self.group_id = group_id
        self.batch_id = batch_id
        self.status = self.QUEUED
        self.attempts = 0
        self.max_attempts = 3
        self.last_attempt = None
        self.error = None
        self.timestamp = datetime.now()
        self.sent_time = None
        self.priority = Priority.NORMAL

    def to_dict(self):
        """Convert status to dictionary for JSON serialization"""
        return {
            'task_id': self.task_id,
            'recipient': self.recipient,
            'subject': self.subject,
            'group_id': self.group_id,
            'batch_id': self.batch_id,
            'status': self.status,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'timestamp': self.timestamp.isoformat(),
            'last_attempt': self.last_attempt.isoformat() if self.last_attempt else None,
            'sent_time': self.sent_time.isoformat() if self.sent_time else None,
            'error': self.error,
            'priority': self.priority
        }


class PriorityEmailQueue:
    def __init__(self):
        self.queue = queue.PriorityQueue()
        self.task_map = {}
        self.counter = itertools.count()

    def put(self, task, priority=Priority.NORMAL):
        """Add a task to the queue with a priority level"""
        task['priority'] = priority
        entry = (priority, next(self.counter), task)
        self.queue.put(entry)

        task_id = task.get('task_id')
        if task_id:
            self.task_map[task_id] = task

        return task_id

    def get(self, timeout=None):
        """Get the next task from the queue based on priority"""
        if self.queue.empty():
            if timeout:
                try:
                    priority, _, task = self.queue.get(timeout=timeout)
                    return task
                except queue.Empty:
                    return None
            return None

        priority, _, task = self.queue.get(block=False)
        task_id = task.get('task_id')

        if task_id and task_id in self.task_map:
            del self.task_map[task_id]

        return task

    def cancel(self, task_id):
        """Cancel a task if it's still in the queue"""
        if task_id in self.task_map:
            task = self.task_map[task_id]
            task['cancelled'] = True
            del self.task_map[task_id]
            return True
        return False

    def size(self):
        """Get queue size"""
        return self.queue.qsize()

    def task_exists(self, task_id):
        """Check if a task exists in the queue"""
        return task_id in self.task_map


# Global email queue and status tracking
email_queue = PriorityEmailQueue()
email_statuses = {}


def get_status_file_path():
    """Get the path to the status file"""
    # Use app root path when available, fallback to current directory
    try:
        from flask import current_app
        app_root = current_app.root_path
    except RuntimeError:
        app_root = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(app_root, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'email_statuses.json')


class EnhancedEmailService:
    def __init__(self, app=None):
        self.app = app
        self._app_ref = None  # Store app reference for background threads
        self.worker_thread = None
        self.running = False
        self.status_save_interval = 60
        self.logger = logging.getLogger('email_service')
        self._shutdown_event = threading.Event()

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app - FIXED VERSION"""
        self.app = app
        # Store app reference for background threads
        self._app_ref = app._get_current_object()

        self.logger.info("Flask app initialized for EnhancedEmailService")

        # Validate configuration on startup
        with app.app_context():
            self._validate_email_config()

        # Load existing statuses
        self._load_statuses()

        # Start worker thread
        if not self.running:
            self.start_worker()

        # Register shutdown handler
        import atexit
        atexit.register(self.stop_worker)

    def _validate_email_config(self):
        """Validate email configuration against config.py settings - IMPROVED VERSION"""
        required_config = {
            'MAIL_SERVER': 'SMTP server address',
            'MAIL_PORT': 'SMTP server port',
            'MAIL_USERNAME': 'SMTP username',
            'MAIL_PASSWORD': 'SMTP password',
            'MAIL_DEFAULT_SENDER': 'Default sender email'
        }

        missing_config = []
        for key, description in required_config.items():
            if not self.app.config.get(key):
                missing_config.append(f"{key} ({description})")

        if missing_config:
            error_msg = f"Missing email configuration: {', '.join(missing_config)}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Validate SSL/TLS configuration
        use_ssl = self.app.config.get('MAIL_USE_SSL', False)
        use_tls = self.app.config.get('MAIL_USE_TLS', False)
        mail_port = self.app.config.get('MAIL_PORT')

        if use_ssl and use_tls:
            self.logger.warning("Both MAIL_USE_SSL and MAIL_USE_TLS are enabled. SSL will take precedence.")

        # Check port/security alignment
        if mail_port == 465 and use_tls and not use_ssl:
            self.logger.warning("Port 465 typically uses SSL, not TLS. Consider using port 587 for TLS")
        elif mail_port == 587 and use_ssl and not use_tls:
            self.logger.warning("Port 587 typically uses TLS, not SSL. Consider using port 465 for SSL")

        # Gmail specific checks
        if 'gmail.com' in self.app.config.get('MAIL_SERVER', ''):
            password = self.app.config.get('MAIL_PASSWORD', '')
            if password and len(password) < 16:
                self.logger.warning("Gmail requires App Password (16 characters) since May 2022")

        self.logger.info(
            f"Email config validated: {self.app.config.get('MAIL_SERVER')}:{self.app.config.get('MAIL_PORT')} "
            f"(SSL: {use_ssl}, TLS: {use_tls})"
        )

    def start_worker(self):
        """Start the email worker thread - IMPROVED VERSION"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.running = True
            self._shutdown_event.clear()
            self.worker_thread = threading.Thread(
                target=self._process_queue,
                daemon=True,
                name="EmailWorker"
            )
            self.worker_thread.start()
            self.logger.info("Email worker thread started")

    def stop_worker(self):
        """Stop the email worker thread - IMPROVED VERSION"""
        self.logger.info("Shutting down email service")
        self.running = False
        self._shutdown_event.set()

        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
            if self.worker_thread.is_alive():
                self.logger.warning("Email worker thread did not shut down gracefully")
            else:
                self.logger.info("Email worker thread stopped")

    def _save_statuses(self):
        """Save email statuses to a file for persistence"""
        try:
            status_file = get_status_file_path()
            statuses = {k: v.to_dict() for k, v in email_statuses.items()}

            with open(status_file, 'w') as f:
                json.dump(statuses, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save email statuses: {str(e)}", exc_info=True)

    def _load_statuses(self):
        """Load email statuses from file on startup"""
        try:
            status_file = get_status_file_path()
            if os.path.exists(status_file):
                with open(status_file, 'r') as f:
                    data = json.load(f)

                global email_statuses
                for task_id, status_dict in data.items():
                    status = EmailStatus(
                        recipient=status_dict['recipient'],
                        subject=status_dict['subject'],
                        task_id=status_dict['task_id'],
                        group_id=status_dict.get('group_id'),
                        batch_id=status_dict.get('batch_id')
                    )
                    status.status = status_dict['status']
                    status.attempts = status_dict['attempts']
                    status.max_attempts = status_dict.get('max_attempts', 3)
                    status.error = status_dict.get('error')
                    status.priority = status_dict.get('priority', Priority.NORMAL)

                    status.timestamp = datetime.fromisoformat(status_dict['timestamp'])
                    if status_dict.get('last_attempt'):
                        status.last_attempt = datetime.fromisoformat(status_dict['last_attempt'])
                    if status_dict.get('sent_time'):
                        status.sent_time = datetime.fromisoformat(status_dict['sent_time'])

                    email_statuses[task_id] = status

                self.logger.info(f"Loaded {len(email_statuses)} email status entries")
        except Exception as e:
            self.logger.error(f"Failed to load email statuses: {str(e)}", exc_info=True)

    def _process_queue(self):
        """Process emails from the queue - FIXED VERSION WITH PROPER CONTEXT"""
        last_save_time = time.time()

        # CRITICAL: Use stored app reference with proper context
        while self.running and not self._shutdown_event.is_set():
            try:
                task = email_queue.get(timeout=1.0)

                if task:
                    task_id = task.get('task_id')
                    if task.get('cancelled', False):
                        self.logger.info(f"Task {task_id} was cancelled. Skipping.")
                        continue

                    # Update status
                    if task_id in email_statuses:
                        email_statuses[task_id].status = EmailStatus.SENDING
                        email_statuses[task_id].attempts += 1
                        email_statuses[task_id].last_attempt = datetime.now()

                    try:
                        # CRITICAL FIX: Use app reference with proper context
                        with self._app_ref.app_context():
                            self._send_email(task)

                        if task_id in email_statuses:
                            email_statuses[task_id].status = EmailStatus.SENT
                            email_statuses[task_id].sent_time = datetime.now()
                            self.logger.info(f"Email sent successfully to {task['recipient']}")

                    except Exception as e:
                        self.logger.error(f"Email sending failed: {str(e)}", exc_info=True)

                        if task_id in email_statuses:
                            status = email_statuses[task_id]
                            status.status = EmailStatus.FAILED
                            status.error = str(e)

                            # Retry logic
                            if status.attempts < status.max_attempts:
                                delay = min(2 ** status.attempts, 60)  # Max 60 second delay
                                self.logger.info(f"Retrying task {task_id} in {delay} seconds")
                                time.sleep(delay)
                                email_queue.put(task, priority=task.get('priority', Priority.NORMAL))

                # Periodic status saving
                current_time = time.time()
                if current_time - last_save_time > self.status_save_interval:
                    self._save_statuses()
                    last_save_time = current_time

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Email worker error: {str(e)}", exc_info=True)
                time.sleep(5)

        self.logger.info("Email worker thread exited")

    def _send_email(self, task):
        """Send an individual email - IMPROVED VERSION"""
        recipient = task['recipient']
        subject = task['subject']
        html_body = task.get('html_body')
        text_body = task.get('text_body')
        attachments = task.get('attachments', [])

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = current_app.config['MAIL_DEFAULT_SENDER']
        msg['To'] = recipient

        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))

        for attachment in attachments:
            self._add_attachment(msg, attachment)

        # Improved retry logic with exponential backoff
        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                server = self._create_smtp_connection()
                server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
                server.send_message(msg)
                server.quit()
                return

            except smtplib.SMTPServerDisconnected as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"SMTP server disconnected after {max_retries} attempts: {str(e)}")
                    raise

                wait_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                self.logger.warning(
                    f"SMTP connection closed, retrying in {wait_time:.2f} seconds (attempt {attempt + 1})")
                time.sleep(wait_time)

            except smtplib.SMTPAuthenticationError as e:
                self.logger.error(f"SMTP authentication failed: {str(e)}")
                self.logger.error(
                    "Check MAIL_USERNAME and MAIL_PASSWORD. For Gmail, ensure you're using an App Password.")
                raise

            except smtplib.SMTPRecipientsRefused as e:
                self.logger.error(f"SMTP recipients refused: {str(e)}")
                raise

            except Exception as e:
                self.logger.error(f"SMTP error on attempt {attempt + 1}: {str(e)}", exc_info=True)
                if attempt == max_retries - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))

    def _create_smtp_connection(self):
        """Create SMTP connection using config.py settings - IMPROVED VERSION"""
        mail_server = current_app.config['MAIL_SERVER']
        mail_port = current_app.config['MAIL_PORT']
        use_ssl = current_app.config.get('MAIL_USE_SSL', False)
        use_tls = current_app.config.get('MAIL_USE_TLS', False)

        try:
            if use_ssl:
                self.logger.debug(f"Creating SMTP_SSL connection to {mail_server}:{mail_port}")
                server = smtplib.SMTP_SSL(mail_server, mail_port, timeout=30)
            else:
                self.logger.debug(f"Creating SMTP connection to {mail_server}:{mail_port}")
                server = smtplib.SMTP(mail_server, mail_port, timeout=30)

                if use_tls:
                    self.logger.debug("Upgrading connection to TLS")
                    server.starttls()

            # Enable debug output in development
            if current_app.debug:
                server.set_debuglevel(1)

            return server

        except Exception as e:
            self.logger.error(f"Failed to create SMTP connection: {str(e)}")
            raise

    def _add_attachment(self, msg, attachment):
        """Add attachment with proper MIME type detection"""
        try:
            filepath = attachment['path']
            filename = attachment['filename']

            if not os.path.exists(filepath):
                self.logger.warning(f"Attachment file not found: {filepath}")
                return

            mime_type, _ = mimetypes.guess_type(filepath)

            with open(filepath, 'rb') as f:
                file_data = f.read()

            if mime_type and mime_type.startswith('image/'):
                attachment_part = MIMEImage(file_data)
            elif mime_type == 'application/pdf':
                attachment_part = MIMEBase('application', 'pdf')
                attachment_part.set_payload(file_data)
                encoders.encode_base64(attachment_part)
            else:
                main_type, sub_type = (mime_type or 'application/octet-stream').split('/', 1)
                attachment_part = MIMEBase(main_type, sub_type)
                attachment_part.set_payload(file_data)
                encoders.encode_base64(attachment_part)

            attachment_part.add_header(
                'Content-Disposition',
                'attachment',
                filename=filename
            )
            msg.attach(attachment_part)

            self.logger.debug(f"Added attachment: {filename} ({mime_type})")

        except Exception as e:
            self.logger.error(f"Failed to add attachment {attachment.get('filename', 'unknown')}: {str(e)}")

    def send_enrollment_confirmation(self, enrollment_id, base_url=None):
        """
        Send enrollment confirmation email - FIXED VERSION

        Args:
            enrollment_id: ID of the enrollment
            base_url: Base URL for verification links

        Returns:
            tuple: (task_id, verification_token)
        """
        # Import here to avoid circular imports
        from models import StudentEnrollment
        from models.enrollment import EnrollmentStatus

        try:
            enrollment = StudentEnrollment.query.get(enrollment_id)
            if not enrollment:
                raise ValueError("Enrollment not found")

            if enrollment.email_verified:
                raise ValueError("Email already verified")

            # Generate verification token
            token = enrollment.generate_email_verification_token()

            # Create verification URL
            if not base_url:
                base_url = current_app.config.get('BASE_URL', 'http://localhost:5000')
            verification_url = f"{base_url}/enrollment/verify-email/{enrollment.id}/{token}"

            # Prepare email context
            context = {
                'enrollment': enrollment,
                'verification_url': verification_url,
                'application_number': enrollment.application_number,
                'full_name': enrollment.full_name,
                'submission_date': enrollment.submitted_at.strftime('%B %d, %Y at %I:%M %p'),
                'receipt_number': enrollment.receipt_number,
                'payment_amount': enrollment.payment_amount,
                'site_name': current_app.config.get('SITE_NAME', 'Programming Course'),
                'support_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com'),
                'timestamp': datetime.now()
            }

            # Render email templates in current context
            html_body = render_template('emails/enrollment_confirmation.html', **context)
            text_body = render_template('emails/enrollment_confirmation.txt', **context)

            # Create task ID and status
            task_id = f"confirm_{enrollment.application_number}_{int(datetime.now().timestamp())}"

            status = EmailStatus(
                recipient=enrollment.email,
                subject=f"Application received - Please verify your email #{enrollment.application_number}",
                task_id=task_id,
                group_id="enrollment_confirmation",
                batch_id=f"enrollment_{enrollment.id}"
            )
            status.priority = Priority.HIGH
            email_statuses[task_id] = status

            # Create email task
            task = {
                'recipient': enrollment.email,
                'subject': f"Application received - Please verify your email #{enrollment.application_number}",
                'html_body': html_body,
                'text_body': text_body,
                'task_id': task_id,
                'group_id': "enrollment_confirmation",
                'batch_id': f"enrollment_{enrollment.id}"
            }

            # Add to priority queue
            email_queue.put(task, Priority.HIGH)

            self.logger.info(f"Enrollment confirmation email queued for {enrollment.email}")
            return task_id, token

        except Exception as e:
            self.logger.error(f"Failed to queue enrollment confirmation email: {str(e)}")
            raise

    def send_simple_test_email(self, recipient, subject, message, priority=Priority.HIGH):
        """Simple method to send a test email - IMPROVED VERSION"""
        task_id = f"simple_test_{int(datetime.now().timestamp())}"

        status = EmailStatus(
            recipient=recipient,
            subject=subject,
            task_id=task_id,
            group_id='test'
        )
        status.priority = priority
        email_statuses[task_id] = status

        # Create simple email content
        html_body = f"""
        <html>
        <body>
            <h2>Test Email</h2>
            <p>{message}</p>
            <p><strong>Task ID:</strong> {task_id}</p>
            <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Configuration:</strong></p>
            <ul>
                <li>MAIL_SERVER: {current_app.config.get('MAIL_SERVER')}</li>
                <li>MAIL_PORT: {current_app.config.get('MAIL_PORT')}</li>
                <li>MAIL_USE_TLS: {current_app.config.get('MAIL_USE_TLS')}</li>
                <li>MAIL_USE_SSL: {current_app.config.get('MAIL_USE_SSL')}</li>
            </ul>
        </body>
        </html>
        """

        text_body = f"""
Test Email

{message}

Task ID: {task_id}
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Configuration:
- MAIL_SERVER: {current_app.config.get('MAIL_SERVER')}
- MAIL_PORT: {current_app.config.get('MAIL_PORT')}
- MAIL_USE_TLS: {current_app.config.get('MAIL_USE_TLS')}
- MAIL_USE_SSL: {current_app.config.get('MAIL_USE_SSL')}
        """

        task = {
            'recipient': recipient,
            'subject': subject,
            'html_body': html_body,
            'text_body': text_body,
            'task_id': task_id,
            'group_id': 'test'
        }

        email_queue.put(task, priority)
        self.logger.info(f"Test email queued for {recipient}")
        return task_id

    def get_queue_stats(self):
        """Get statistics about the email queue"""
        stats = {
            'queued': 0,
            'sending': 0,
            'sent': 0,
            'failed': 0,
            'cancelled': 0,
            'total': len(email_statuses)
        }

        # Count by status
        for status in email_statuses.values():
            if status.status in stats:
                stats[status.status] += 1

        stats['queue_size'] = email_queue.size()
        stats['worker_alive'] = self.worker_thread and self.worker_thread.is_alive()

        return stats

    def get_email_status(self, task_id):
        """Get status of an email task"""
        if task_id in email_statuses:
            return email_statuses[task_id].to_dict()
        return None
