# services/enrollment_service.py
"""
Complete enrollment service with proper email integration fixes.
This version maintains all existing functionality while fixing email context issues.
"""

import os
import logging
from flask import current_app, render_template, url_for
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta

from app.utils.enhanced_email import Priority
from app.models.enrollment import StudentEnrollment, EnrollmentStatus, PaymentStatus
from app.models.participant import Participant
from app.config import Config
from app.extensions import db, email_service


class EnrollmentService:
    """Service class for student enrollment management operations with fixed email integration."""

    @staticmethod
    def create_enrollment(personal_info, contact_info, learning_resources_info, payment_info, additional_info=None):
        """Create a new enrollment application with all information including payment."""
        logger = logging.getLogger('enrollment_service')

        try:
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
            logger.info(f"Enrollment created successfully: {enrollment.application_number}")
            return enrollment

        except Exception as e:
            logger.error(f"Failed to create enrollment: {str(e)}")
            # Clean up file if database update fails
            if 'upload_path' in locals() and os.path.exists(upload_path):
                os.remove(upload_path)
            db.session.rollback()
            raise

    @staticmethod
    def create_enrollment_with_confirmation(personal_info, contact_info, learning_resources_info,
                                            payment_info, additional_info=None, base_url=None):
        """Create enrollment and send confirmation email - FIXED VERSION."""
        logger = logging.getLogger('enrollment_service')

        # Create enrollment first
        enrollment = EnrollmentService.create_enrollment(
            personal_info, contact_info, learning_resources_info, payment_info, additional_info
        )

        # Initialize return values
        task_id = None
        token = None

        # Send confirmation email - isolated from enrollment creation
        try:
            # Generate verification token - FIXED
            token = enrollment.generate_email_verification_token()

            # IMPORTANT: Refresh the enrollment to ensure token is in database
            db.session.refresh(enrollment)

            # Build verification URL
            if base_url:
                verification_url = f"{base_url}/enrollment/verify-email/{enrollment.id}/{token}"
            else:
                verification_url = url_for('enrollment.verify_email',
                                           enrollment_id=enrollment.id,
                                           token=token,
                                           _external=True)

            logger.info(f"Generated verification URL: {verification_url}")

            # Use the unified send_notification method
            task_id = email_service.send_notification(
                recipient=enrollment.email,
                template='enrollment_confirmation',
                subject=f"Verify your email - Application #{enrollment.application_number}",
                template_context={
                    'enrollment': enrollment,
                    'verification_url': verification_url,
                    'application_number': enrollment.application_number,
                    'full_name': enrollment.full_name,
                    'verification_token': token,
                    'expiry_hours': 24,
                    'steps_remaining': 'verify email → payment review → enrollment decision'
                },
                priority=Priority.HIGH,
                group_id='enrollment_confirmation',
                batch_id=f"enrollment_confirmation_{enrollment.id}"
            )

            logger.info(
                f"Enrollment confirmation email queued: {task_id} for application {enrollment.application_number}")

        except Exception as e:
            # CRITICAL: Don't fail enrollment creation if email fails
            logger.error(f"Failed to queue confirmation email for enrollment {enrollment.id}: {str(e)}")

        return enrollment, task_id, token

    @staticmethod
    def update_enrollment_info(enrollment_id, updates):
        """Update enrollment information (only specific fields allowed, no editing once enrolled)."""
        logger = logging.getLogger('enrollment_service')

        try:
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
            logger.info(f"Enrollment {enrollment.application_number} updated: {changes}")

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
                    logger.info(f"Enrollment update notification email queued: {email_task_id}")
                except Exception as e:
                    logger.warning(f"Failed to queue update notification email: {e}")

            return enrollment, changes

        except Exception as e:
            logger.error(f"Failed to update enrollment info: {str(e)}")
            db.session.rollback()
            raise

    @staticmethod
    def update_receipt(enrollment_id, receipt_file, receipt_number, payment_amount):
        """Update receipt information (only if payment not yet verified)."""
        logger = logging.getLogger('enrollment_service')

        try:
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

            # Save new file
            receipt_file.save(upload_path)

            # Update enrollment record
            enrollment.receipt_upload_path = f"registration_receipts/{filename}"
            enrollment.receipt_number = receipt_number
            enrollment.payment_amount = payment_amount
            enrollment.payment_date = datetime.now()  # Use Python datetime

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
                logger.info(f"Receipt update notification email queued: {email_task_id}")
            except Exception as e:
                logger.warning(f"Failed to queue receipt update notification email: {e}")

            logger.info(f"Receipt updated for enrollment {enrollment.application_number}")
            return enrollment, filename

        except Exception as e:
            # Clean up new file if database update fails
            if 'upload_path' in locals() and os.path.exists(upload_path):
                os.remove(upload_path)
            db.session.rollback()
            logger.error(f"Failed to update receipt: {str(e)}")
            raise

    @staticmethod
    def can_edit_enrollment(enrollment_id):
        """Check if enrollment can be edited and return what fields are editable."""
        try:
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

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error checking edit permissions: {str(e)}")
            return False, f"Error checking permissions: {str(e)}"

    @staticmethod
    def send_email_verification(enrollment_id, base_url=None):
        """Send email verification request - FIXED VERSION."""
        logger = logging.getLogger('enrollment_service')

        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()
            if not enrollment:
                raise ValueError("Enrollment not found")

            if enrollment.email_verified:
                raise ValueError("Email is already verified")

            # Generate NEW verification token
            token = enrollment.generate_email_verification_token()

            # IMPORTANT: Refresh to ensure token is saved
            db.session.refresh(enrollment)

            if base_url:
                verification_url = f"{base_url}/enrollment/verify-email/{enrollment.id}/{token}"
            else:
                verification_url = url_for('enrollment.verify_email',
                                           enrollment_id=enrollment.id,
                                           token=token,
                                           _external=True)

            logger.info(f"Generated resend verification URL: {verification_url}")

            # Template context
            template_context = {
                'enrollment': enrollment,
                'verification_url': verification_url,
                'token': token,
                'expires_hours': 24
            }

            # Send email using the email service
            task_id = email_service.send_notification(
                recipient=enrollment.email,
                template='email_verification',
                subject=f'Verify your email address - {current_app.config.get("SITE_NAME", "Programming Course")}',
                template_context=template_context
            )

            logger.info(f"Email verification resent for enrollment {enrollment.application_number}")
            return task_id, token

        except Exception as e:
            logger.error(f"Failed to send email verification for enrollment {enrollment_id}: {str(e)}")
            raise

    @staticmethod
    def send_enrollment_status_email(enrollment_id, email_type, custom_data=None):
        """Send status update emails (approved, rejected, info_updated, receipt_updated, etc.) - FIXED VERSION."""
        logger = logging.getLogger('enrollment_service')

        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment:
                raise ValueError("Enrollment not found")

            # Email type configurations
            email_configs = {
                'approved': {
                    'template': 'enrollment_approved',
                    'subject': f"🎉 Enrollment approved - Welcome to Programming Course!",
                    'priority': 'HIGH'
                },
                'rejected': {
                    'template': 'enrollment_rejected',
                    'subject': f"Application update - Application #{enrollment.application_number}",
                    'priority': 'NORMAL'
                },
                'payment_verified': {
                    'template': 'payment_verified',
                    'subject': f"Payment verified - Application #{enrollment.application_number}",
                    'priority': 'NORMAL'
                },
                'info_updated': {
                    'template': 'enrollment_info_updated',
                    'subject': f"Information updated - Application #{enrollment.application_number}",
                    'priority': 'NORMAL'
                },
                'receipt_updated': {
                    'template': 'receipt_updated',
                    'subject': f"Receipt updated - Application #{enrollment.application_number}",
                    'priority': 'NORMAL'
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

            # Render email templates within current context
            html_body = render_template(f'emails/{config["template"]}.html', **context)
            text_body = render_template(f'emails/{config["template"]}.txt', **context)

            # Create task ID
            task_id = f"{email_type}_{enrollment.application_number}_{int(datetime.now().timestamp())}"

            # Import priority and status classes
            from app.utils.enhanced_email import Priority, email_queue, email_statuses, EmailStatus

            # Determine priority
            priority = Priority.HIGH if config['priority'] == 'HIGH' else Priority.NORMAL

            # Create status tracking
            status = EmailStatus(
                recipient=enrollment.email,
                subject=config['subject'],
                task_id=task_id,
                group_id=f"enrollment_{email_type}",
                batch_id=f"{email_type}_{enrollment.id}"
            )
            status.priority = priority
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
            email_queue.put(task, priority)

            logger.info(f"Status email queued for enrollment {enrollment.application_number}: {email_type}")
            return task_id

        except Exception as e:
            logger.error(f"Failed to queue status email: {str(e)}")
            return None

    @staticmethod
    def verify_email(enrollment_id, token):
        """Verify email with provided token - IMPROVED VERSION."""
        logger = logging.getLogger('enrollment_service')

        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment:
                logger.error(f"Enrollment not found for ID: {enrollment_id}")
                raise ValueError("Enrollment not found")

            logger.info(f"Verifying email for enrollment {enrollment.application_number}")
            logger.info(f"Provided token: {token}")
            logger.info(f"Stored token: {enrollment.email_verification_token}")
            logger.info(f"Email already verified: {enrollment.email_verified}")

            if enrollment.email_verified:
                logger.warning(f"Email already verified for enrollment {enrollment.application_number}")
                return True  # Already verified is considered success

            # Verify the token
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
                        logger.info(f"Payment verified email queued: {email_task_id}")
                    except Exception as e:
                        logger.warning(f"Failed to queue payment verified email: {e}")

                # Ensure the database is updated
                db.session.commit()
                logger.info(f"Email verified successfully for enrollment {enrollment.application_number}")
                return True
            else:
                logger.error(f"Token verification failed for enrollment {enrollment.application_number}")
                raise ValueError("Invalid or expired verification token")

        except Exception as e:
            logger.error(f"Email verification failed: {str(e)}")
            db.session.rollback()
            raise

    # Core enrollment management methods
    @staticmethod
    def get_enrollment_by_id(enrollment_id, include_sensitive=False):
        """Get enrollment by ID with optimized query."""
        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment:
                raise ValueError("Enrollment not found")

            if not include_sensitive:
                # Return dict without sensitive fields
                return enrollment.to_dict()

            return enrollment

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting enrollment by ID: {str(e)}")
            raise

    @staticmethod
    def get_enrollment_by_application_number(application_number):
        """Get enrollment by application number."""
        try:
            enrollment = (
                db.session.query(StudentEnrollment)
                .filter_by(application_number=application_number)
                .first()
            )

            if not enrollment:
                raise ValueError("Enrollment application not found")

            return enrollment

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting enrollment by application number: {str(e)}")
            raise

    @staticmethod
    def get_enrollment_by_email(email):
        """Get enrollment by email address."""
        try:
            enrollment = (
                db.session.query(StudentEnrollment)
                .filter_by(email=email)
                .first()
            )

            return enrollment

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting enrollment by email: {str(e)}")
            return None

    @staticmethod
    def verify_payment(enrollment_id, verified_by_user_id):
        """Admin verification of payment."""
        logger = logging.getLogger('enrollment_service')

        try:
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
                logger.info(f"Payment verified email queued: {email_task_id}")
            except Exception as e:
                logger.warning(f"Failed to queue payment verified email: {e}")

            logger.info(f"Payment verified for enrollment {enrollment.application_number}")
            return enrollment

        except Exception as e:
            logger.error(f"Payment verification failed: {str(e)}")
            raise

    @staticmethod
    def get_enrollments_for_admin(status=None, payment_status=None, verified_only=False,
                                  ready_for_processing=False, limit=50, offset=0):
        """Get enrollments for admin dashboard with optimized queries."""
        try:
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

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting enrollments for admin: {str(e)}")
            raise

    @staticmethod
    def get_enrollment_statistics():
        """Get enrollment statistics for dashboard."""
        try:
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

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting enrollment statistics: {str(e)}")
            raise

    @staticmethod
    def process_enrollment_to_participant(enrollment_id, classroom=None, processed_by_user_id=None):
        """
        Process approved enrollment into participant record.

        Args:
            enrollment_id: ID of enrollment to process
            classroom: Admin-selected classroom (may be overridden by auto-assignment)
            processed_by_user_id: ID of user processing the enrollment

        Returns:
            tuple: (participant, enrollment) objects
        """
        logger = logging.getLogger('enrollment_service')

        try:
            # Get enrollment
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment:
                raise ValueError("Enrollment not found")

            logger.info(f"Processing enrollment {enrollment.application_number} to participant")

            # Create participant using model method (handles classroom assignment and sessions)
            participant = enrollment.enroll_as_participant(
                classroom=classroom,
                processed_by_user_id=processed_by_user_id
            )

            # Create user account for participant
            user, password = participant.create_user_account()

            # Commit all changes
            db.session.commit()

            # Send approval email with login credentials and session info
            try:
                custom_data = {
                    'participant_id': participant.unique_id,
                    'username': user.username,
                    'temporary_password': password,
                    'login_url': f"{current_app.config.get('BASE_URL', '')}/auth/login",
                    'approval_date': enrollment.processed_at.strftime('%B %d, %Y'),
                    'session_info': {
                        'saturday_session': participant.saturday_session.time_slot if participant.saturday_session else 'Not assigned',
                        'sunday_session': participant.sunday_session.time_slot if participant.sunday_session else 'Not assigned',
                        'classroom': participant.classroom,
                        'classroom_name': (
                            'Computer Lab (Laptop Required)' if participant.classroom == current_app.config[
                                'LAPTOP_CLASSROOM']
                            else 'Regular Classroom (No Laptop Required)'
                        )
                    }
                }

                email_task_id = EnrollmentService.send_enrollment_status_email(
                    enrollment_id, 'approved', custom_data
                )

                logger.info(
                    f"Approval email queued: {email_task_id}" if email_task_id else "Approval email failed to queue")

            except Exception as e:
                # Don't fail the enrollment process if email fails
                logger.warning(f"Failed to queue approval email: {e}")

            logger.info(
                f"Successfully processed enrollment {enrollment.application_number} "
                f"to participant {participant.unique_id} in classroom {participant.classroom}"
            )

            return participant, enrollment

        except ValueError as e:
            logger.error(f"Validation error processing enrollment {enrollment_id}: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to process enrollment {enrollment_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def reject_enrollment(enrollment_id, reason, rejected_by_user_id):
        """Reject an enrollment application."""
        logger = logging.getLogger('enrollment_service')

        try:
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
                logger.info(f"Enrollment rejection email queued: {email_task_id}")
            except Exception as e:
                logger.warning(f"Failed to queue rejection email: {e}")

            logger.info(f"Enrollment {enrollment.application_number} rejected")
            return enrollment

        except Exception as e:
            logger.error(f"Failed to reject enrollment: {str(e)}")
            raise

    @staticmethod
    def cancel_enrollment(enrollment_id):
        """Cancel an enrollment application."""
        logger = logging.getLogger('enrollment_service')

        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment:
                raise ValueError("Enrollment not found")

            if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
                raise ValueError("Cannot cancel - already enrolled as participant")

            enrollment.cancel_enrollment()
            db.session.commit()

            logger.info(f"Enrollment {enrollment.application_number} cancelled")
            return enrollment

        except Exception as e:
            logger.error(f"Failed to cancel enrollment: {str(e)}")
            raise

    @staticmethod
    def search_enrollments(search_term, limit=20):
        """Search enrollments by name, email, or application number."""
        try:
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

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error searching enrollments: {str(e)}")
            raise

    @staticmethod
    def get_receipt_file_path(enrollment_id):
        """Get the full file path for enrollment receipt."""
        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()

            if not enrollment or not enrollment.receipt_upload_path:
                return None

            return os.path.join(Config.BASE_DIR, 'uploads', enrollment.receipt_upload_path)

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting receipt file path: {str(e)}")
            return None

    @staticmethod
    def delete_receipt(enrollment_id):
        """Delete uploaded receipt (only if not yet enrolled)."""
        logger = logging.getLogger('enrollment_service')

        try:
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

            logger.info(f"Receipt deleted for enrollment {enrollment.application_number}")
            return enrollment

        except Exception as e:
            logger.error(f"Failed to delete receipt: {str(e)}")
            raise

    @staticmethod
    def resend_verification_email(enrollment_id, base_url=None):
        """Resend verification email for an enrollment."""
        logger = logging.getLogger('enrollment_service')

        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()
            if not enrollment:
                raise ValueError("Enrollment not found")

            if enrollment.email_verified:
                raise ValueError("Email is already verified")

            # Send verification email using existing method
            task_id, token = EnrollmentService.send_email_verification(enrollment_id, base_url)

            logger.info(f"Verification email resent for enrollment {enrollment.application_number}")
            return task_id, token

        except Exception as e:
            logger.error(f"Failed to resend verification email: {str(e)}")
            raise

    @staticmethod
    def get_email_status(enrollment_id):
        """Get email status for an enrollment."""
        try:
            enrollment = db.session.query(StudentEnrollment).filter_by(id=enrollment_id).first()
            if not enrollment:
                raise ValueError("Enrollment not found")

            # Check for email task ID in enrollment record
            task_id = getattr(enrollment, 'email_task_id', None)

            if task_id and email_service:
                # Get status from email service
                email_status = email_service.get_email_status(task_id)
                if email_status:
                    return email_status

            # Return basic status based on enrollment state
            return {
                'status': 'sent' if enrollment.email_verified else 'unknown',
                'email_verified': enrollment.email_verified,
                'enrollment_status': enrollment.enrollment_status,
                'payment_status': enrollment.payment_status
            }

        except Exception as e:
            logging.getLogger('enrollment_service').error(f"Error getting email status: {str(e)}")
            return {'status': 'error', 'error': str(e)}