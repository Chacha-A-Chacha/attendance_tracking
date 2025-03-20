# utils/email_service.py
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from flask import current_app, render_template
from datetime import datetime
import threading
import queue
import time

# Email task queue
email_queue = queue.Queue()
# For tracking email statuses
email_statuses = {}


class EmailStatus:
    QUEUED = 'queued'
    SENDING = 'sending'
    SENT = 'sent'
    FAILED = 'failed'

    def __init__(self, recipient, subject, task_id=None):
        self.recipient = recipient
        self.subject = subject
        self.task_id = task_id or f"email_{int(datetime.now().timestamp())}_{recipient}"
        self.status = self.QUEUED
        self.attempts = 0
        self.last_attempt = None
        self.error = None
        self.timestamp = datetime.now()


class EmailService:
    def __init__(self, app=None):
        self.app = app
        self.worker_thread = None
        self.running = False

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app"""
        self.app = app

        # Start worker thread if not running
        if not self.running:
            self.start_worker()

    def start_worker(self):
        """Start the email worker thread"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue)
            self.worker_thread.daemon = True
            self.worker_thread.start()

    def stop_worker(self):
        """Stop the email worker thread"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=1.0)

    def _process_queue(self):
        """Process emails from the queue"""
        while self.running:
            try:
                # Get task from queue with a timeout
                task = email_queue.get(timeout=1.0)
                if task:
                    try:
                        # Update status
                        task_id = task.get('task_id')
                        if task_id in email_statuses:
                            email_statuses[task_id].status = EmailStatus.SENDING
                            email_statuses[task_id].attempts += 1
                            email_statuses[task_id].last_attempt = datetime.now()

                        # Send email
                        self._send_email(task)

                        # Update status to sent
                        if task_id in email_statuses:
                            email_statuses[task_id].status = EmailStatus.SENT

                    except Exception as e:
                        # Handle failure - implement retry logic
                        current_app.logger.error(f"Email sending failed: {str(e)}")

                        if task_id in email_statuses:
                            email_statuses[task_id].status = EmailStatus.FAILED
                            email_statuses[task_id].error = str(e)

                        # If fewer than 3 attempts, requeue
                        if task.get('attempts', 0) < 3:
                            task['attempts'] = task.get('attempts', 0) + 1
                            # Wait before retrying - exponential backoff
                            time.sleep(2 ** task['attempts'])
                            email_queue.put(task)
                    finally:
                        email_queue.task_done()
            except queue.Empty:
                # No tasks in queue, just continue
                continue

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

        # Attach text and HTML versions
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))

        # Attach any files
        for attachment in attachments:
            with open(attachment['path'], 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-Disposition', 'attachment', filename=attachment['filename'])
                msg.attach(img)

        # Send email using SMTP
        with smtplib.SMTP_SSL(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
            server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
            server.send_message(msg)

    def send_qr_code(self, recipient, participant):
        """Send QR code to a participant"""
        # Create a task ID
        task_id = f"qrcode_{participant.unique_id}_{int(datetime.now().timestamp())}"

        # Create task status
        status = EmailStatus(recipient, "Your QR Code for the Programming Course", task_id)
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
            'attempts': 0
        }

        # Add to queue
        email_queue.put(task)

        return task_id

    def get_email_status(self, task_id):
        """Get status of an email task"""
        if task_id in email_statuses:
            return {
                'task_id': task_id,
                'status': email_statuses[task_id].status,
                'attempts': email_statuses[task_id].attempts,
                'timestamp': email_statuses[task_id].timestamp.isoformat(),
                'last_attempt': email_statuses[task_id].last_attempt.isoformat() if email_statuses[
                    task_id].last_attempt else None,
                'error': email_statuses[task_id].error
            }
        return None

    def get_queue_stats(self):
        """Get statistics about the email queue"""
        stats = {
            'queued': 0,
            'sending': 0,
            'sent': 0,
            'failed': 0,
            'total': len(email_statuses)
        }

        for status in email_statuses.values():
            if status.status in stats:
                stats[status.status] += 1

        stats['queue_size'] = email_queue.qsize()

        return stats
    