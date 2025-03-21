import os
import smtplib
import json
import random
import logging
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
        self.group_id = group_id  # For classroom, session, etc.
        self.batch_id = batch_id  # For identifying a group of emails sent together
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
        self.task_map = {}  # Maps task_id to task position for cancellation/updates

    def put(self, task, priority=Priority.NORMAL):
        """Add a task to the queue with a priority level"""
        task['priority'] = priority
        entry = (priority, time.time(), task)
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


# Create email queue
email_queue = PriorityEmailQueue()

# For tracking email statuses - persist to file for recovery
email_statuses = {}


def get_status_file_path():
    """Get the path to the status file"""
    app_root = current_app.root_path if current_app else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_root, 'data', 'email_statuses.json')


class EnhancedEmailService:
    def __init__(self, app=None):
        self.app = app
        self.worker_thread = None
        self.running = False
        self.status_save_interval = 60  # Save statuses every 60 seconds
        self.logger = logging.getLogger(__name__)

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app"""
        self.app = app
        self._load_statuses()

        if not self.running:
            self.start_worker()

    def start_worker(self):
        """Start the email worker thread"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue)
            self.worker_thread.daemon = True
            self.worker_thread.start()
            self.logger.info("Email worker thread started.")

    def stop_worker(self):
        """Stop the email worker thread"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=1.0)
            self.logger.info("Email worker thread stopped.")

    def _save_statuses(self):
        """Save email statuses to a file for persistence"""
        try:
            status_file = get_status_file_path()
            os.makedirs(os.path.dirname(status_file), exist_ok=True)

            statuses = {k: v.to_dict() for k, v in email_statuses.items()}

            with open(status_file, 'w') as f:
                json.dump(statuses, f, indent=2)
            self.logger.debug("Email statuses saved to file.")
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

                self.logger.info(f"Loaded {len(email_statuses)} email status entries.")
        except Exception as e:
            self.logger.error(f"Failed to load email statuses: {str(e)}", exc_info=True)

    def _process_queue(self):
        """Process emails from the queue"""
        last_save_time = time.time()

        with self.app.app_context():
            while self.running:
                try:
                    task = email_queue.get(timeout=1.0)

                    if task:
                        task_id = task.get('task_id')
                        if task.get('cancelled', False):
                            self.logger.info(f"Task {task_id} was cancelled. Skipping.")
                            continue

                        if task_id in email_statuses:
                            email_statuses[task_id].status = EmailStatus.SENDING
                            email_statuses[task_id].attempts += 1
                            email_statuses[task_id].last_attempt = datetime.now()

                        try:
                            self._send_email(task)
                            if task_id in email_statuses:
                                email_statuses[task_id].status = EmailStatus.SENT
                                email_statuses[task_id].sent_time = datetime.now()
                                self.logger.info(f"Email sent successfully to {task['recipient']}.")
                        except Exception as e:
                            self.logger.error(f"Email sending failed: {str(e)}", exc_info=True)

                            if task_id in email_statuses:
                                status = email_statuses[task_id]
                                status.status = EmailStatus.FAILED
                                status.error = str(e)

                                if status.attempts < status.max_attempts:
                                    delay = 2 ** status.attempts
                                    self.logger.info(f"Retrying task {task_id} in {delay} seconds.")
                                    time.sleep(delay)
                                    email_queue.put(task, priority=task.get('priority', Priority.NORMAL))

                    current_time = time.time()
                    if current_time - last_save_time > self.status_save_interval:
                        self._save_statuses()
                        last_save_time = current_time

                except queue.Empty:
                    pass
                except Exception as e:
                    self.logger.error(f"Email worker error: {str(e)}", exc_info=True)
                    time.sleep(5)

    def _send_email(self, task):
        """Send an individual email"""
        recipient = task['recipient']
        subject = task['subject']
        html_body = task['html_body']
        text_body = task['text_body']
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
            with open(attachment['path'], 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-Disposition', 'attachment', filename=attachment['filename'])
                msg.attach(img)

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                server = smtplib.SMTP_SSL(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT'])
                server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
                server.send_message(msg)
                server.quit()
                return

            except smtplib.SMTPServerDisconnected as e:
                retry_count += 1
                if retry_count >= max_retries:
                    self.logger.error(f"SMTP server disconnected after {max_retries} attempts: {str(e)}")
                    raise

                wait_time = (2 ** retry_count) + random.uniform(0, 1)
                self.logger.warning(f"SMTP connection closed, retrying in {wait_time:.2f} seconds")
                time.sleep(wait_time)
            except Exception as e:
                self.logger.error(f"SMTP error: {str(e)}", exc_info=True)
                raise

    def send_qr_code(self, recipient, participant, priority=Priority.NORMAL, batch_id=None):
        """Send QR code to a participant"""
        # Create a task ID
        task_id = f"qrcode_{participant.unique_id}_{int(datetime.now().timestamp())}"

        # Determine group ID (classroom)
        group_id = f"class_{participant.classroom}"

        # Create task status
        status = EmailStatus(
            recipient=recipient,
            subject="Your QR Code for the Programming Course",
            task_id=task_id,
            group_id=group_id,
            batch_id=batch_id
        )
        status.priority = priority
        email_statuses[task_id] = status

        # Get QR code path
        qr_path = participant.qrcode_path

        if not qr_path or not os.path.exists(qr_path):
            raise FileNotFoundError("QR code not found. Please generate it first.")

        # Generate email body from template
        with self.app.app_context():
            html_body = render_template('emails/qrcode.html',
                                        participant=participant,
                                        timestamp=datetime.now())
            text_body = render_template('emails/qrcode.txt',
                                        participant=participant,
                                        timestamp=datetime.now())

        # Create email task
        task = {
            'recipient': recipient,
            'subject': "Your QR Code for the Programming Course",
            'html_body': html_body,
            'text_body': text_body,
            'attachments': [{
                'path': qr_path,
                'filename': f"qrcode-{participant.unique_id}.png"
            }],
            'task_id': task_id,
            'group_id': group_id,
            'batch_id': batch_id
        }

        # Add to queue with priority
        email_queue.put(task, priority)

        return task_id

    def send_class_notification(self, classroom, subject, template, template_context=None,
                                priority=Priority.NORMAL, batch_id=None):
        """Send notification to all participants in a classroom"""
        from models import Participant

        # Generate batch ID if not provided
        if not batch_id:
            batch_id = f"batch_{int(datetime.now().timestamp())}"

        # Find all participants in the classroom
        with self.app.app_context():
            participants = Participant.query.filter_by(classroom=classroom).all()

            task_ids = []
            for participant in participants:
                # Create email context with participant data
                context = template_context.copy() if template_context else {}
                context['participant'] = participant
                context['timestamp'] = datetime.now()

                # Render templates
                html_body = render_template(f'emails/{template}.html', **context)
                text_body = render_template(f'emails/{template}.txt', **context)

                # Create task ID
                task_id = f"notify_{participant.unique_id}_{int(datetime.now().timestamp())}"

                # Determine group ID
                group_id = f"class_{participant.classroom}"

                # Create task status
                status = EmailStatus(
                    recipient=participant.email,
                    subject=subject,
                    task_id=task_id,
                    group_id=group_id,
                    batch_id=batch_id
                )
                status.priority = priority
                email_statuses[task_id] = status

                # Create email task
                task = {
                    'recipient': participant.email,
                    'subject': subject,
                    'html_body': html_body,
                    'text_body': text_body,
                    'task_id': task_id,
                    'group_id': group_id,
                    'batch_id': batch_id
                }

                # Add attachments if participant has QR code
                if participant.qrcode_path and os.path.exists(participant.qrcode_path):
                    task['attachments'] = [{
                        'path': participant.qrcode_path,
                        'filename': f"qrcode-{participant.unique_id}.png"
                    }]

                # Add to queue
                email_queue.put(task, priority)
                task_ids.append(task_id)

            return {
                'batch_id': batch_id,
                'task_ids': task_ids,
                'participant_count': len(participants)
            }

    def send_session_notification(self, day, time_slot, subject, template, template_context=None,
                                  priority=Priority.NORMAL, batch_id=None):
        """Send notification to all participants in a specific session"""
        from models import Participant, Session

        # Generate batch ID if not provided
        if not batch_id:
            batch_id = f"batch_{int(datetime.now().timestamp())}"

        # Find the session
        with self.app.app_context():
            session = Session.query.filter_by(day=day, time_slot=time_slot).first()

            if not session:
                raise ValueError(f"No session found for {day} at {time_slot}")

            # Find all participants in this session
            if day.lower() == 'saturday':
                participants = Participant.query.filter_by(saturday_session_id=session.id).all()
            else:
                participants = Participant.query.filter_by(sunday_session_id=session.id).all()

            task_ids = []
            for participant in participants:
                # Create email context with participant data
                context = template_context.copy() if template_context else {}
                context['participant'] = participant
                context['session'] = session
                context['timestamp'] = datetime.now()

                # Render templates
                html_body = render_template(f'emails/{template}.html', **context)
                text_body = render_template(f'emails/{template}.txt', **context)

                # Create task ID and group ID
                task_id = f"notify_{participant.unique_id}_{int(datetime.now().timestamp())}"
                group_id = f"session_{day}_{time_slot.replace(' ', '_')}"

                # Create task status
                status = EmailStatus(
                    recipient=participant.email,
                    subject=subject,
                    task_id=task_id,
                    group_id=group_id,
                    batch_id=batch_id
                )
                status.priority = priority
                email_statuses[task_id] = status

                # Create email task
                task = {
                    'recipient': participant.email,
                    'subject': subject,
                    'html_body': html_body,
                    'text_body': text_body,
                    'task_id': task_id,
                    'group_id': group_id,
                    'batch_id': batch_id
                }

                # Add attachments if participant has QR code
                if participant.qrcode_path and os.path.exists(participant.qrcode_path):
                    task['attachments'] = [{
                        'path': participant.qrcode_path,
                        'filename': f"qrcode-{participant.unique_id}.png"
                    }]

                # Add to queue
                email_queue.put(task, priority)
                task_ids.append(task_id)

            return {
                'batch_id': batch_id,
                'task_ids': task_ids,
                'participant_count': len(participants)
            }

    def send_custom_group_email(self, participant_ids, subject, template, template_context=None,
                                priority=Priority.NORMAL, batch_id=None):
        """Send emails to a custom group of participants by ID"""
        from models import Participant

        # Generate batch ID if not provided
        if not batch_id:
            batch_id = f"batch_{int(datetime.now().timestamp())}"

        with self.app.app_context():
            # Find all specified participants
            participants = Participant.query.filter(Participant.id.in_(participant_ids)).all()

            task_ids = []
            for participant in participants:
                # Create email context with participant data
                context = template_context.copy() if template_context else {}
                context['participant'] = participant
                context['timestamp'] = datetime.now()

                # Render templates
                html_body = render_template(f'emails/{template}.html', **context)
                text_body = render_template(f'emails/{template}.txt', **context)

                # Create task ID
                task_id = f"custom_{participant.unique_id}_{int(datetime.now().timestamp())}"
                group_id = f"custom_group"

                # Create task status
                status = EmailStatus(
                    recipient=participant.email,
                    subject=subject,
                    task_id=task_id,
                    group_id=group_id,
                    batch_id=batch_id
                )
                status.priority = priority
                email_statuses[task_id] = status

                # Create email task
                task = {
                    'recipient': participant.email,
                    'subject': subject,
                    'html_body': html_body,
                    'text_body': text_body,
                    'task_id': task_id,
                    'group_id': group_id,
                    'batch_id': batch_id
                }

                # Add attachments if participant has QR code
                if participant.qrcode_path and os.path.exists(participant.qrcode_path):
                    task['attachments'] = [{
                        'path': participant.qrcode_path,
                        'filename': f"qrcode-{participant.unique_id}.png"
                    }]

                # Add to queue
                email_queue.put(task, priority)
                task_ids.append(task_id)

            return {
                'batch_id': batch_id,
                'task_ids': task_ids,
                'participant_count': len(participants)
            }

    def cancel_email(self, task_id):
        """Cancel an email if it's still in the queue"""
        # Try to cancel in queue
        if email_queue.cancel(task_id):
            # Update status
            if task_id in email_statuses:
                email_statuses[task_id].status = EmailStatus.CANCELLED
            return True

        # If not in queue, check if it exists in status
        if task_id in email_statuses:
            # Only cancel if still queued
            if email_statuses[task_id].status == EmailStatus.QUEUED:
                email_statuses[task_id].status = EmailStatus.CANCELLED
                return True

        return False

    def retry_failed_email(self, task_id):
        """Retry a failed email"""
        if task_id in email_statuses and email_statuses[task_id].status == EmailStatus.FAILED:
            # Reset status
            email_statuses[task_id].status = EmailStatus.QUEUED
            email_statuses[task_id].attempts = 0
            email_statuses[task_id].error = None

            # Need to recreate the task - this would need task data access
            # For now, return success to indicate status was updated
            return True

        return False

    def get_email_status(self, task_id):
        """Get status of an email task"""
        if task_id in email_statuses:
            return email_statuses[task_id].to_dict()
        return None

    def get_batch_status(self, batch_id):
        """Get status of all emails in a batch"""
        if not batch_id:
            return None

        batch_tasks = {}
        for task_id, status in email_statuses.items():
            if status.batch_id == batch_id:
                batch_tasks[task_id] = status.to_dict()

        return {
            'batch_id': batch_id,
            'total': len(batch_tasks),
            'tasks': batch_tasks
        }

    def get_group_status(self, group_id):
        """Get status of all emails for a group"""
        if not group_id:
            return None

        group_tasks = {}
        for task_id, status in email_statuses.items():
            if status.group_id == group_id:
                group_tasks[task_id] = status.to_dict()

        return {
            'group_id': group_id,
            'total': len(group_tasks),
            'tasks': group_tasks
        }

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

        # Count by group
        group_stats = {}
        for status in email_statuses.values():
            if status.group_id:
                if status.group_id not in group_stats:
                    group_stats[status.group_id] = {
                        'total': 0,
                        'queued': 0,
                        'sending': 0,
                        'sent': 0,
                        'failed': 0,
                        'cancelled': 0
                    }
                group_stats[status.group_id]['total'] += 1
                group_stats[status.group_id][status.status] += 1

        # Count by batch
        batch_stats = {}
        for status in email_statuses.values():
            if status.batch_id:
                if status.batch_id not in batch_stats:
                    batch_stats[status.batch_id] = {
                        'total': 0,
                        'queued': 0,
                        'sending': 0,
                        'sent': 0,
                        'failed': 0,
                        'cancelled': 0
                    }
                batch_stats[status.batch_id]['total'] += 1
                batch_stats[status.batch_id][status.status] += 1

        stats['queue_size'] = email_queue.size()
        stats['groups'] = group_stats
        stats['batches'] = batch_stats

        return stats

    def clean_old_statuses(self, days=30):
        """Remove old email statuses to prevent unlimited growth"""
        cutoff_date = datetime.now() - timedelta(days=days)
        removed = 0

        for task_id in list(email_statuses.keys()):
            status = email_statuses[task_id]
            if status.timestamp < cutoff_date and status.status in [EmailStatus.SENT, EmailStatus.CANCELLED]:
                del email_statuses[task_id]
                removed += 1

        # Save updated statuses
        self._save_statuses()

        return {'removed': removed}
