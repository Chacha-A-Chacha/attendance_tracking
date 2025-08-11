# services/enrollment_service.py
import os
from flask import current_app, render_template, url_for
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
from models.enrollment import StudentEnrollment, EnrollmentStatus, PaymentStatus
from models.participant import Participant
from config import Config
from app import db
import uuid
from datetime import datetime, timedelta


class EnrollmentService:
    """Service class for student enrollment management operations."""

    @staticmethod
    def create_enrollment(personal_info, contact_info, learning_resources_info, payment_info, additional_info=None):
        """Create a new enrollment application with all information including payment."""
        # Check if email already exists
        if db.session.query(StudentEnrollment.query.filter_by(email=contact_info['email']).exists()).scalar():
            raise ValueError(f"Email '{contact_info['email']}' already has an enrollment application")

        # Check if email exists in participants
        if db.session.query(Participant.query.filter_by(email=contact_info['email']).exists()).scalar():
            raise ValueError(f"Email '{contact_info['email']}' is already enrolled as a participant")

        # Validate and handle receipt upload
        receipt_file = payment_info.get('receipt_file')
        if not receipt_file or not Config.allowed_file(receipt_file.filename, 'receipt'):
            raise ValueError("Valid receipt file is required")

        enrollment = StudentEnrollment(
            # Personal information
            surname=personal_info['surname'],
            first_name=personal_info['first_name'],
            second_name=personal_info.get('second_name'),

            # Contact information
            email=contact_info['email'],
            phone=contact_info['phone'],

            # Learning resources
            has_laptop=learning_resources_info.get('has_laptop', False),
            laptop_brand=learning_resources_info.get('laptop_brand'),
            laptop_model=learning_resources_info.get('laptop_model'),
            needs_laptop_rental=learning_resources_info.get('needs_laptop_rental', False),

            # Additional information
            emergency_contact=additional_info.get('emergency_contact') if additional_info else None,
            emergency_phone=additional_info.get('emergency_phone') if additional_info else None,
            special_requirements=additional_info.get('special_requirements') if additional_info else None,
            how_did_you_hear=additional_info.get('how_did_you_hear') if additional_info else None,
            previous_attendance=additional_info.get('previous_attendance', False) if additional_info else False
        )

        db.session.add(enrollment)
        db.session.flush()  # Get the enrollment ID and application number

        try:
            # Generate secure filename using application number
            filename = Config.generate_receipt_filename(
                'registration',
                enrollment.application_number,
                receipt_file.filename
            )

            # Get upload path and save file
            upload_path = Config.get_upload_path('registration_receipt', filename)
            receipt_file.save(upload_path)

            # Update enrollment with payment information
            enrollment.receipt_upload_path = f"registration_receipts/{filename}"
            enrollment.mark_payment_received(
                payment_info['receipt_number'],
                payment_info['payment_amount']
            )

            # Set initial status to payment pending
            enrollment.enrollment_status = EnrollmentStatus.PAYMENT_PENDING

            db.session.commit()
            return enrollment

        except Exception as e:
            # Clean up file if database update fails
            if 'upload_path' in locals() and os.path.exists(upload_path):
                os.remove(upload_path)
            db.session.rollback()
            raise ValueError(f"Failed to process enrollment: {str(e)}")

    @staticmethod
    def create_enrollment_with_confirmation(personal_info, contact_info, learning_resources_info,
                                            payment_info, additional_info=None, base_url=None):
        """Create enrollment and automatically send confirmation email with verification."""
        # Create enrollment with all information including payment
        enrollment = EnrollmentService.create_enrollment(
            personal_info, contact_info, learning_resources_info, payment_info, additional_info
        )

        # Send confirmation email with verification link
        try:
            task_id, token = EnrollmentService.send_enrollment_confirmation_email(
                enrollment.id, base_url
            )
            current_app.logger.info(f"Enrollment confirmation email queued: {task_id}")

            return enrollment, task_id, token
        except Exception as e:
            current_app.logger.error(f"Failed to queue confirmation email: {e}")
            return enrollment, None, None

    @staticmethod
    def update_enrollment_info(enrollment_id, updates):
        """Update enrollment information (only specific fields allowed, no editing once enrolled)."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        # Prevent editing if already enrolled as participant
        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            raise ValueError("Cannot modify enrollment - already enrolled as participant")

        # Prevent editing if rejected
        if enrollment.enrollment_status == EnrollmentStatus.REJECTED:
            raise ValueError("Cannot modify rejected enrollment")

        # Define fields that can be updated
        allowed_updates = {
            # Contact information (limited)
            'phone',

            # Learning resources
            'has_laptop',
            'laptop_brand',
            'laptop_model',
            'needs_laptop_rental',

            # Additional information
            'emergency_contact',
            'emergency_phone',
            'special_requirements',
            'how_did_you_hear',
            'previous_attendance'
        }

        # Fields that are NEVER editable after submission
        protected_fields = {
            'surname', 'first_name', 'second_name', 'email',
            'receipt_number', 'payment_amount', 'receipt_upload_path',
            'application_number', 'enrollment_status', 'payment_status'
        }

        # Filter updates to only allowed fields
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_updates}

        # Check for attempts to update protected fields
        attempted_protected = {k for k in updates.keys() if k in protected_fields}
        if attempted_protected:
            raise ValueError(f"Cannot update protected fields: {', '.join(attempted_protected)}")

        if not filtered_updates:
            raise ValueError("No valid fields to update")

        # Track what changed for logging
        changes = {}
        for field, new_value in filtered_updates.items():
            old_value = getattr(enrollment, field)
            if old_value != new_value:
                changes[field] = {'old': old_value, 'new': new_value}
                setattr(enrollment, field, new_value)

        if not changes:
            raise ValueError("No changes detected")

        # Log the changes
        current_app.logger.info(f"Enrollment {enrollment.application_number} updated: {changes}")

        db.session.commit()

        # Send update notification email if significant changes
        significant_fields = {'phone', 'has_laptop', 'emergency_contact'}
        if any(field in changes for field in significant_fields):
            try:
                custom_data = {
                    'changes': changes,
                    'update_date': datetime.now().strftime('%B %d, %Y at %I:%M %p')
                }
                email_task_id = EnrollmentService.send_enrollment_status_email(
                    enrollment_id, 'info_updated', custom_data
                )
                current_app.logger.info(f"Enrollment update notification email queued: {email_task_id}")
            except Exception as e:
                current_app.logger.warning(f"Failed to queue update notification email: {e}")

        return enrollment, changes

    @staticmethod
    def update_receipt(enrollment_id, receipt_file, receipt_number, payment_amount):
        """Update receipt information (only if payment not yet verified)."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        # Prevent editing if already enrolled as participant
        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            raise ValueError("Cannot update receipt - already enrolled as participant")

        # Prevent editing if payment already verified
        if enrollment.payment_status == PaymentStatus.VERIFIED:
            raise ValueError("Cannot update receipt - payment already verified by admin")

        # Validate new receipt file
        if not receipt_file or not Config.allowed_file(receipt_file.filename, 'receipt'):
            raise ValueError("Valid receipt file is required")

        # Store old file path for cleanup
        old_file_path = None
        if enrollment.receipt_upload_path:
            old_file_path = os.path.join(Config.BASE_DIR, 'uploads', enrollment.receipt_upload_path)

        # Generate new filename
        filename = Config.generate_receipt_filename(
            'registration',
            enrollment.application_number,
            receipt_file.filename
        )

        # Get upload path
        upload_path = Config.get_upload_path('registration_receipt', filename)

        try:
            # Save new file
            receipt_file.save(upload_path)

            # Update enrollment record
            enrollment.receipt_upload_path = f"registration_receipts/{filename}"
            enrollment.receipt_number = receipt_number
            enrollment.payment_amount = payment_amount
            enrollment.payment_date = func.now()

            # Reset payment verification status (admin needs to verify again)
            enrollment.payment_status = PaymentStatus.PAID
            enrollment.payment_verified_at = None
            enrollment.payment_verified_by = None

            db.session.commit()

            # Clean up old file if it exists
            if old_file_path and os.path.exists(old_file_path):
                os.remove(old_file_path)

            # Send receipt update notification
            try:
                custom_data = {
                    'old_receipt_number': enrollment.receipt_number,
                    'new_receipt_number': receipt_number,
                    'update_date': datetime.now().strftime('%B %d, %Y at %I:%M %p')
                }
                email_task_id = EnrollmentService.send_enrollment_status_email(
                    enrollment_id, 'receipt_updated', custom_data
                )
                current_app.logger.info(f"Receipt update notification email queued: {email_task_id}")
            except Exception as e:
                current_app.logger.warning(f"Failed to queue receipt update notification email: {e}")

            return enrollment, filename

        except Exception as e:
            # Clean up new file if database update fails
            if os.path.exists(upload_path):
                os.remove(upload_path)
            db.session.rollback()
            raise ValueError(f"Failed to update receipt: {str(e)}")

    @staticmethod
    def can_edit_enrollment(enrollment_id):
        """Check if enrollment can be edited and return what fields are editable."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            return False, "Enrollment not found"

        # Cannot edit if enrolled
        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            return False, "Already enrolled as participant"

        # Cannot edit if rejected
        if enrollment.enrollment_status == EnrollmentStatus.REJECTED:
            return False, "Enrollment has been rejected"

        # Define what can be edited based on current status
        always_editable = {
            'phone', 'emergency_contact', 'emergency_phone',
            'special_requirements', 'how_did_you_hear', 'previous_attendance'
        }

        conditionally_editable = {
            'has_laptop', 'laptop_brand', 'laptop_model', 'needs_laptop_rental'
        }

        # Receipt can be updated if not yet verified
        receipt_editable = enrollment.payment_status != PaymentStatus.VERIFIED

        return True, {
            'info_fields': always_editable | conditionally_editable,
            'receipt_editable': receipt_editable,
            'current_status': enrollment.enrollment_status,
            'payment_status': enrollment.payment_status
        }

    # Email Integration Methods
    @staticmethod
    def send_enrollment_confirmation_email(enrollment_id, base_url=None):
        """Send confirmation email after complete enrollment submission (including receipt)."""
        from ..utils.enhanced_email import email_queue, email_statuses, EmailStatus, Priority

        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if enrollment.email_verified:
            raise ValueError("Email already verified")

        # Generate verification token using model method
        token = enrollment.generate_email_verification_token()
        db.session.commit()

        # Create verification URL
        if not base_url:
            base_url = current_app.config.get('BASE_URL', 'http://localhost:5000')
        verification_url = f"{base_url}/enrollment/verify-email/{enrollment.id}/{token}"

        # Prepare email context with receipt acknowledgment
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
            'next_steps': [
                'Click the verification link in this email',
                'Wait for admin to verify your payment',
                'Receive enrollment decision',
                'Get your login credentials (if approved)'
            ],
            'timestamp': datetime.now()
        }

        # Render email templates
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

        return task_id, token

    @staticmethod
    def send_enrollment_status_email(enrollment_id, email_type, custom_data=None):
        """Send status update emails (approved, rejected, info_updated, receipt_updated, etc.)."""
        from ..utils.enhanced_email import email_queue, email_statuses, EmailStatus, Priority

        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        # Email type configurations
        email_configs = {
            'approved': {
                'template': 'enrollment_approved',
                'subject': f"🎉 Enrollment approved - Welcome to Programming Course!",
                'priority': Priority.HIGH
            },
            'rejected': {
                'template': 'enrollment_rejected',
                'subject': f"Application update - Application #{enrollment.application_number}",
                'priority': Priority.NORMAL
            },
            'payment_verified': {
                'template': 'payment_verified',
                'subject': f"Payment verified - Application #{enrollment.application_number}",
                'priority': Priority.NORMAL
            },
            'info_updated': {
                'template': 'enrollment_info_updated',
                'subject': f"Information updated - Application #{enrollment.application_number}",
                'priority': Priority.NORMAL
            },
            'receipt_updated': {
                'template': 'receipt_updated',
                'subject': f"Receipt updated - Application #{enrollment.application_number}",
                'priority': Priority.NORMAL
            }
        }

        if email_type not in email_configs:
            raise ValueError(f"Invalid email type: {email_type}")

        config = email_configs[email_type]

        # Base context
        context = {
            'enrollment': enrollment,
            'application_number': enrollment.application_number,
            'full_name': enrollment.full_name,
            'site_name': current_app.config.get('SITE_NAME', 'Programming Course'),
            'support_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com'),
            'timestamp': datetime.now()
        }

        # Add custom data
        if custom_data:
            context.update(custom_data)

        # Render email templates
        html_body = render_template(f'emails/{config["template"]}.html', **context)
        text_body = render_template(f'emails/{config["template"]}.txt', **context)

        # Create task ID and status
        task_id = f"{email_type}_{enrollment.application_number}_{int(datetime.now().timestamp())}"

        status = EmailStatus(
            recipient=enrollment.email,
            subject=config['subject'],
            task_id=task_id,
            group_id=f"enrollment_{email_type}",
            batch_id=f"{email_type}_{enrollment.id}"
        )
        status.priority = config['priority']
        email_statuses[task_id] = status

        # Create email task
        task = {
            'recipient': enrollment.email,
            'subject': config['subject'],
            'html_body': html_body,
            'text_body': text_body,
            'task_id': task_id,
            'group_id': f"enrollment_{email_type}",
            'batch_id': f"{email_type}_{enrollment.id}"
        }

        # Add to queue
        email_queue.put(task, config['priority'])

        return task_id

    # Core enrollment management methods (keeping all from Version 1)
    @staticmethod
    def get_enrollment_by_id(enrollment_id, include_sensitive=False):
        """Get enrollment by ID with optimized query."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if not include_sensitive:
            # Return dict without sensitive fields
            return enrollment.to_dict()

        return enrollment

    @staticmethod
    def get_enrollment_by_application_number(application_number):
        """Get enrollment by application number."""
        enrollment = (
            db.session.query(StudentEnrollment)
            .filter_by(application_number=application_number)
            .first()
        )

        if not enrollment:
            raise ValueError("Enrollment application not found")

        return enrollment

    @staticmethod
    def get_enrollment_by_email(email):
        """Get enrollment by email address."""
        enrollment = (
            db.session.query(StudentEnrollment)
            .filter_by(email=email)
            .first()
        )

        return enrollment

    @staticmethod
    def verify_email(enrollment_id, token):
        """Verify email with provided token."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if enrollment.verify_email(token):
            # Update enrollment status if payment is also verified
            if (enrollment.payment_status == PaymentStatus.VERIFIED and
                    enrollment.enrollment_status == EnrollmentStatus.PAYMENT_PENDING):
                enrollment.enrollment_status = EnrollmentStatus.PAYMENT_VERIFIED

                # Send payment verified email
                try:
                    email_task_id = EnrollmentService.send_enrollment_status_email(
                        enrollment_id, 'payment_verified'
                    )
                    current_app.logger.info(f"Payment verified email queued: {email_task_id}")
                except Exception as e:
                    current_app.logger.warning(f"Failed to queue payment verified email: {e}")

            db.session.commit()
            return True
        else:
            raise ValueError("Invalid or expired verification token")

    @staticmethod
    def verify_payment(enrollment_id, verified_by_user_id):
        """Admin verification of payment."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if not enrollment.is_paid:
            raise ValueError("No payment recorded for this enrollment")

        enrollment.verify_payment(verified_by_user_id)
        db.session.commit()

        # Send payment verified email
        try:
            email_task_id = EnrollmentService.send_enrollment_status_email(
                enrollment_id, 'payment_verified'
            )
            current_app.logger.info(f"Payment verified email queued: {email_task_id}")
        except Exception as e:
            current_app.logger.warning(f"Failed to queue payment verified email: {e}")

        return enrollment

    @staticmethod
    def get_enrollments_for_admin(status=None, payment_status=None, verified_only=False,
                                  ready_for_processing=False, limit=50, offset=0):
        """Get enrollments for admin dashboard with optimized queries."""
        query = db.session.query(StudentEnrollment)

        # Apply filters
        if status:
            query = query.filter(StudentEnrollment.enrollment_status == status)

        if payment_status:
            query = query.filter(StudentEnrollment.payment_status == payment_status)

        if verified_only:
            query = query.filter(StudentEnrollment.email_verified == True)

        if ready_for_processing:
            query = query.filter(
                and_(
                    StudentEnrollment.email_verified == True,
                    StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                    StudentEnrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
                )
            )

        # Order by submission date (newest first)
        query = query.order_by(StudentEnrollment.submitted_at.desc())

        # Apply pagination
        query = query.offset(offset).limit(limit)

        return query.all()

    @staticmethod
    def get_enrollment_statistics():
        """Get enrollment statistics for dashboard."""
        stats = {}

        # Total enrollments
        stats['total'] = db.session.query(func.count(StudentEnrollment.id)).scalar()

        # By status
        status_counts = (
            db.session.query(
                StudentEnrollment.enrollment_status,
                func.count(StudentEnrollment.id)
            )
            .group_by(StudentEnrollment.enrollment_status)
            .all()
        )
        stats['by_status'] = {status: count for status, count in status_counts}

        # By payment status
        payment_counts = (
            db.session.query(
                StudentEnrollment.payment_status,
                func.count(StudentEnrollment.id)
            )
            .group_by(StudentEnrollment.payment_status)
            .all()
        )
        stats['by_payment_status'] = {status: count for status, count in payment_counts}

        # Ready for processing
        stats['ready_for_processing'] = (
            db.session.query(func.count(StudentEnrollment.id))
            .filter(
                and_(
                    StudentEnrollment.email_verified == True,
                    StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                    StudentEnrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
                )
            )
            .scalar()
        )

        # Recent submissions (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        stats['recent_submissions'] = (
            db.session.query(func.count(StudentEnrollment.id))
            .filter(StudentEnrollment.submitted_at >= week_ago)
            .scalar()
        )

        return stats

    @staticmethod
    def process_enrollment_to_participant(enrollment_id, classroom, processed_by_user_id):
        """Process approved enrollment into participant record."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if not enrollment.is_ready_for_enrollment():
            raise ValueError("Enrollment not ready for processing")

        try:
            participant = enrollment.enroll_as_participant(classroom, processed_by_user_id)

            # Create user account for participant
            user, password = participant.create_user_account()

            db.session.commit()

            # Send approval email with login credentials
            try:
                custom_data = {
                    'participant_id': participant.unique_id,
                    'username': user.username,
                    'temporary_password': password,
                    'login_url': f"{current_app.config.get('BASE_URL', '')}/login",
                    'approval_date': enrollment.processed_at.strftime('%B %d, %Y')
                }

                email_task_id = EnrollmentService.send_enrollment_status_email(
                    enrollment_id, 'approved', custom_data
                )
                current_app.logger.info(f"Enrollment approval email queued: {email_task_id}")
            except Exception as e:
                current_app.logger.warning(f"Failed to queue approval email: {e}")

            return participant, enrollment

        except Exception as e:
            db.session.rollback()
            raise ValueError(f"Failed to process enrollment: {str(e)}")

    @staticmethod
    def reject_enrollment(enrollment_id, reason, rejected_by_user_id):
        """Reject an enrollment application."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            raise ValueError("Cannot reject - already enrolled as participant")

        enrollment.reject_enrollment(reason, rejected_by_user_id)
        db.session.commit()

        # Send rejection email
        try:
            custom_data = {
                'rejection_reason': reason,
                'rejection_date': enrollment.processed_at.strftime('%B %d, %Y')
            }

            email_task_id = EnrollmentService.send_enrollment_status_email(
                enrollment_id, 'rejected', custom_data
            )
            current_app.logger.info(f"Enrollment rejection email queued: {email_task_id}")
        except Exception as e:
            current_app.logger.warning(f"Failed to queue rejection email: {e}")

        return enrollment

    @staticmethod
    def cancel_enrollment(enrollment_id):
        """Cancel an enrollment application."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            raise ValueError("Cannot cancel - already enrolled as participant")

        enrollment.cancel_enrollment()
        db.session.commit()

        return enrollment

    @staticmethod
    def search_enrollments(search_term, limit=20):
        """Search enrollments by name, email, or application number."""
        search_pattern = f"%{search_term}%"

        enrollments = (
            db.session.query(StudentEnrollment)
            .filter(
                or_(
                    StudentEnrollment.first_name.ilike(search_pattern),
                    StudentEnrollment.surname.ilike(search_pattern),
                    StudentEnrollment.email.ilike(search_pattern),
                    StudentEnrollment.application_number.ilike(search_pattern)
                )
            )
            .order_by(StudentEnrollment.submitted_at.desc())
            .limit(limit)
            .all()
        )

        return enrollments

    @staticmethod
    def get_receipt_file_path(enrollment_id):
        """Get the full file path for enrollment receipt."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment or not enrollment.receipt_upload_path:
            return None

        return os.path.join(Config.BASE_DIR, 'uploads', enrollment.receipt_upload_path)

    @staticmethod
    def delete_receipt(enrollment_id):
        """Delete uploaded receipt (only if not yet enrolled)."""
        enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

        if not enrollment:
            raise ValueError("Enrollment not found")

        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            raise ValueError("Cannot delete receipt - already enrolled")

        # Get file path
        if enrollment.receipt_upload_path:
            file_path = os.path.join(Config.BASE_DIR, 'uploads', enrollment.receipt_upload_path)

            # Delete file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)

        # Reset payment information
        enrollment.receipt_upload_path = None
        enrollment.receipt_number = None
        enrollment.payment_amount = None
        enrollment.payment_date = None
        enrollment.is_paid = False
        enrollment.payment_status = PaymentStatus.UNPAID

        # Reset enrollment status if it was payment-pending
        if enrollment.enrollment_status == EnrollmentStatus.PAYMENT_PENDING:
            enrollment.enrollment_status = EnrollmentStatus.PENDING

        db.session.commit()

        return enrollment
