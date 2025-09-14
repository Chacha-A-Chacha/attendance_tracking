# services/enrollment_service.py
"""
Complete enrollment service with proper email integration fixes.
This version maintains all existing functionality while fixing email context issues.
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Any

from flask import current_app, render_template, url_for
from sqlalchemy import and_, or_, func, case, text, exists
from sqlalchemy.orm import load_only, joinedload
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from app.utils.enhanced_email import Priority
from app.models.enrollment import StudentEnrollment, EnrollmentStatus, PaymentStatus
from app.models.participant import Participant
from app.config import Config
from app.extensions import db, email_service


class BulkEnrollmentMode:
    """Bulk enrollment processing modes."""
    CONSTRAINT_BASED = 'constraint_based'  # Only process ready students
    ADMIN_OVERRIDE = 'admin_override'  # Process regardless of constraints


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



    @staticmethod
    def get_bulk_enrollment_candidates_optimized(
            constraints: Optional[Dict] = None,
            mode: str = BulkEnrollmentMode.CONSTRAINT_BASED,
            limit: int = 500,
            offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get enrollment candidates using optimized database queries.

        Args:
            constraints: Filter constraints (email_verified, has_laptop, payment_status)
            mode: Processing mode (constraint_based or admin_override)
            limit: Maximum results to return
            offset: Query offset for pagination

        Returns:
            dict: Comprehensive results with analysis and candidates
        """
        logger = logging.getLogger('enrollment_service')

        try:
            # Build optimized base query
            base_query = EnrollmentService._build_enrollment_candidates_query(
                constraints=constraints,
                mode=mode,
                for_preview=True
            )

            # Get total count (optimized with index)
            # count_query = base_query.with_only_columns([func.count(StudentEnrollment.id)])
            count_query = db.session.query(func.count(StudentEnrollment.id)).filter(
                StudentEnrollment.enrollment_status != EnrollmentStatus.ENROLLED
            )
            if mode == BulkEnrollmentMode.CONSTRAINT_BASED:
                count_query = count_query.filter(
                    and_(
                        StudentEnrollment.email_verified == True,
                        StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                        StudentEnrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
                    )
                )
            total_count = count_query.scalar()

            # Get preview data with optimized loading
            preview_query = base_query.options(
                load_only(
                    StudentEnrollment.id,
                    StudentEnrollment.application_number,
                    StudentEnrollment.first_name,
                    StudentEnrollment.surname,
                    StudentEnrollment.email,
                    StudentEnrollment.has_laptop,
                    StudentEnrollment.email_verified,
                    StudentEnrollment.payment_status,
                    StudentEnrollment.enrollment_status,
                    StudentEnrollment.submitted_at
                )
            ).limit(limit).offset(offset)

            preview_enrollments = preview_query.all()

            # Generate analysis using database aggregation
            analysis = EnrollmentService._generate_bulk_analysis_optimized(
                base_query, mode, constraints
            )

            # Capacity impact analysis
            capacity_impact = EnrollmentService._analyze_bulk_capacity_impact_optimized(
                preview_enrollments
            )

            # Constraint override warnings
            override_warnings = []
            if mode == BulkEnrollmentMode.ADMIN_OVERRIDE:
                override_warnings = EnrollmentService._analyze_constraint_overrides(
                    preview_enrollments
                )

            logger.info(f"Bulk candidates query: {total_count} total, {len(preview_enrollments)} preview")

            return {
                'success': True,
                'total_count': total_count,
                'preview_enrollments': preview_enrollments,
                'analysis': analysis,
                'capacity_impact': capacity_impact,
                'constraints_applied': constraints or {},
                'processing_mode': mode,
                'override_warnings': override_warnings,
                'query_performance': {
                    'total_candidates': total_count,
                    'preview_loaded': len(preview_enrollments),
                    'database_optimized': True
                }
            }

        except Exception as e:
            logger.error(f"Error getting bulk enrollment candidates: {str(e)}")
            raise

    @staticmethod
    def bulk_process_enrollments_flexible(
            enrollment_ids: List[str],
            mode: str = BulkEnrollmentMode.CONSTRAINT_BASED,
            constraints: Optional[Dict] = None,
            processed_by_user_id: Optional[str] = None,
            send_emails: bool = True,
            batch_size: int = 25,
            force_override: bool = False
    ) -> Dict[str, Any]:
        """
        Flexible bulk enrollment processing with constraint validation and override capability.

        Args:
            enrollment_ids: List of enrollment UUID strings to process
            mode: Processing mode (constraint_based or admin_override)
            constraints: Optional constraints for validation
            processed_by_user_id: Admin user ID performing operation
            send_emails: Whether to send approval emails
            batch_size: Batch size for processing
            force_override: Force processing even with constraint violations

        Returns:
            dict: Comprehensive processing results with audit trail
        """
        logger = logging.getLogger('enrollment_service')

        # Validate inputs
        if not enrollment_ids:
            raise ValueError("No enrollment IDs provided")

        if len(enrollment_ids) > 1000:  # Increased limit for flexible processing
            raise ValueError("Too many enrollments selected (max 1000)")

        try:
            # Pre-validation and eligibility check
            eligibility_result = EnrollmentService._validate_bulk_enrollment_eligibility(
                enrollment_ids, mode, constraints, force_override
            )

            if not eligibility_result['eligible_ids'] and not force_override:
                return {
                    'success': False,
                    'message': 'No eligible enrollments found for processing',
                    'eligibility_check': eligibility_result
                }

            # Initialize comprehensive results tracking
            results = {
                'total_requested': len(enrollment_ids),
                'processed': 0,
                'failed': 0,
                'skipped': 0,
                'override_processed': 0,
                'created_participants': [],
                'failed_enrollments': [],
                'skipped_enrollments': [],
                'override_enrollments': [],
                'session_assignments': {'Saturday': {}, 'Sunday': {}},
                'classroom_distribution': {},
                'batch_results': [],
                'processing_mode': mode,
                'force_override_used': force_override,
                'constraints_applied': constraints or {},
                'eligibility_check': eligibility_result,
                'audit_trail': [],
                'started_at': datetime.now(),
                'completed_at': None
            }

            # Process eligible enrollments in optimized batches
            eligible_ids = eligibility_result['eligible_ids'] if not force_override else enrollment_ids
            total_batches = (len(eligible_ids) + batch_size - 1) // batch_size

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(eligible_ids))
                batch_ids = eligible_ids[start_idx:end_idx]

                logger.info(
                    f"Processing batch {batch_num + 1}/{total_batches} ({len(batch_ids)} enrollments) - Mode: {mode}")

                batch_result = EnrollmentService._process_enrollment_batch_optimized(
                    batch_ids, mode, constraints, processed_by_user_id, send_emails, force_override
                )

                # Update comprehensive results
                EnrollmentService._merge_batch_results(results, batch_result)

                # Commit batch for memory management and consistency
                db.session.commit()

                logger.info(f"Batch {batch_num + 1} completed: {batch_result['processed']} processed, "
                            f"{batch_result['failed']} failed, {batch_result['skipped']} skipped, "
                            f"{batch_result['override_processed']} override processed")

            # Handle skipped enrollments (those not in eligible list)
            if not force_override:
                skipped_ids = set(enrollment_ids) - set(eligible_ids)
                for enrollment_id in skipped_ids:
                    skip_reason = eligibility_result['ineligible_reasons'].get(enrollment_id, 'Unknown reason')
                    results['skipped_enrollments'].append({
                        'enrollment_id': enrollment_id,
                        'reason': skip_reason,
                        'skipped_at': datetime.now().isoformat()
                    })
                    results['skipped'] += 1

            # Finalize results
            results['completed_at'] = datetime.now()
            results['duration'] = (results['completed_at'] - results['started_at']).total_seconds()

            # Audit logging for override operations
            if mode == BulkEnrollmentMode.ADMIN_OVERRIDE or force_override:
                EnrollmentService._audit_bulk_enrollment_operation(results, processed_by_user_id)

            logger.info(f"Flexible bulk enrollment completed: {results['processed']} participants created, "
                        f"{results['override_processed']} override processed, {results['failed']} failed, "
                        f"{results['skipped']} skipped in {results['duration']:.1f}s")

            return results

        except Exception as e:
            db.session.rollback()
            logger.error(f"Flexible bulk enrollment processing failed: {str(e)}")
            raise

    @staticmethod
    def _build_enrollment_candidates_query(
            constraints: Optional[Dict] = None,
            mode: str = BulkEnrollmentMode.CONSTRAINT_BASED,
            for_preview: bool = False
    ):
        """
        Build optimized database query for enrollment candidates.
        Core query builder with database-level filtering.
        """
        # Base query with critical exclusions (cannot process already enrolled)
        query = db.session.query(StudentEnrollment).filter(
            StudentEnrollment.enrollment_status != EnrollmentStatus.ENROLLED
        )

        # Mode-specific filtering
        if mode == BulkEnrollmentMode.CONSTRAINT_BASED:
            # Standard constraint-based mode: only process "ready" enrollments
            query = query.filter(
                and_(
                    StudentEnrollment.email_verified == True,
                    StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                    StudentEnrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
                )
            )
        elif mode == BulkEnrollmentMode.ADMIN_OVERRIDE:
            # Override mode: exclude only final states but allow processing of incomplete applications
            query = query.filter(
                StudentEnrollment.enrollment_status.notin_([
                    EnrollmentStatus.ENROLLED,  # Already participants
                    EnrollmentStatus.CANCELLED  # Explicitly cancelled
                ])
            )

        # Apply additional constraints if provided
        if constraints:
            # Email verification filter (database boolean)
            if 'email_verified' in constraints:
                email_verified = constraints['email_verified']
                if isinstance(email_verified, str):
                    email_verified = email_verified.lower() == 'true'
                query = query.filter(StudentEnrollment.email_verified == email_verified)

            # Laptop status filter (database boolean)
            if 'has_laptop' in constraints:
                has_laptop = constraints['has_laptop']
                if isinstance(has_laptop, str):
                    has_laptop = has_laptop.lower() == 'true'
                query = query.filter(StudentEnrollment.has_laptop == has_laptop)

            # Payment status filter (database enum)
            if 'payment_status' in constraints and constraints['payment_status']:
                query = query.filter(StudentEnrollment.payment_status == constraints['payment_status'])

            # Date range filters
            if 'submitted_after' in constraints:
                query = query.filter(StudentEnrollment.submitted_at >= constraints['submitted_after'])
            if 'submitted_before' in constraints:
                query = query.filter(StudentEnrollment.submitted_at <= constraints['submitted_before'])

        # Optimize query ordering for consistent results
        query = query.order_by(StudentEnrollment.submitted_at.desc(), StudentEnrollment.id.asc())

        return query

    @staticmethod
    def _validate_bulk_enrollment_eligibility(
            enrollment_ids: List[str],
            mode: str,
            constraints: Optional[Dict] = None,
            force_override: bool = False
    ) -> Dict[str, Any]:
        """
        Validate eligibility of enrollments for bulk processing.

        Args:
            enrollment_ids: List of enrollment UUID strings
            mode: Processing mode
            constraints: Optional constraints
            force_override: Whether to force override

        Returns:
            dict: Eligibility results with UUID strings
        """
        logger = logging.getLogger('enrollment_service')

        # Fast eligibility check using optimized query
        eligibility_query = db.session.query(
            StudentEnrollment.id,
            StudentEnrollment.application_number,
            StudentEnrollment.enrollment_status,
            StudentEnrollment.email_verified,
            StudentEnrollment.payment_status,
            StudentEnrollment.has_laptop
        ).filter(StudentEnrollment.id.in_(enrollment_ids))

        enrollments = eligibility_query.all()

        eligible_ids: List[str] = []
        ineligible_reasons: Dict[str, str] = {}
        override_candidates = []

        for enrollment in enrollments:
            enrollment_id: str = enrollment.id

            # Critical exclusion: cannot process already enrolled participants
            if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
                ineligible_reasons[enrollment_id] = 'Already enrolled as participant'
                continue

            # Mode-specific validation
            if mode == BulkEnrollmentMode.CONSTRAINT_BASED:
                # Standard validation
                if not enrollment.email_verified:
                    ineligible_reasons[enrollment_id] = 'Email not verified'
                elif enrollment.payment_status != PaymentStatus.VERIFIED:
                    ineligible_reasons[enrollment_id] = 'Payment not verified by admin'
                elif enrollment.enrollment_status != EnrollmentStatus.PAYMENT_VERIFIED:
                    ineligible_reasons[enrollment_id] = f'Status: {enrollment.enrollment_status}'
                else:
                    eligible_ids.append(enrollment_id)

            elif mode == BulkEnrollmentMode.ADMIN_OVERRIDE:
                # Override mode: allow processing of most statuses
                if enrollment.enrollment_status == EnrollmentStatus.CANCELLED:
                    if force_override:
                        override_candidates.append({
                            'id': enrollment_id,
                            'application_number': enrollment.application_number,
                            'issue': 'Cancelled enrollment',
                            'override_required': True
                        })
                        eligible_ids.append(enrollment_id)
                    else:
                        ineligible_reasons[enrollment_id] = 'Enrollment cancelled (use force override)'
                else:
                    # Track constraint violations for audit
                    violations = []
                    if not enrollment.email_verified:
                        violations.append('email_unverified')
                    if enrollment.payment_status != PaymentStatus.VERIFIED:
                        violations.append('payment_unverified')

                    if violations:
                        override_candidates.append({
                            'id': enrollment_id,
                            'application_number': enrollment.application_number,
                            'violations': violations,
                            'override_required': False
                        })

                    eligible_ids.append(enrollment_id)

        # Validate requested IDs exist
        found_ids = {str(e.id) for e in enrollments}
        missing_ids = set(enrollment_ids) - found_ids
        for missing_id in missing_ids:
            ineligible_reasons[missing_id] = 'Enrollment not found'

        return {
            'eligible_ids': eligible_ids,
            'ineligible_reasons': ineligible_reasons,
            'override_candidates': override_candidates,
            'validation_summary': {
                'total_requested': len(enrollment_ids),
                'eligible': len(eligible_ids),
                'ineligible': len(ineligible_reasons),
                'override_candidates': len(override_candidates),
                'missing': len(missing_ids)
            }
        }

    @staticmethod
    def _process_enrollment_batch_optimized(
            enrollment_ids: List[str],
            mode: str,
            constraints: Optional[Dict],
            processed_by_user_id: Optional[str],
            send_emails: bool,
            force_override: bool = False
    ) -> Dict[str, Any]:
        """
        Process a single batch with optimized database operations and flexible constraints.
        """
        logger = logging.getLogger('enrollment_service')

        # Batch results tracking
        batch_result = {
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'override_processed': 0,
            'created_participants': [],
            'failed_enrollments': [],
            'skipped_enrollments': [],
            'override_enrollments': [],
            'session_assignments': {'Saturday': {}, 'Sunday': {}},
            'classroom_distribution': {},
            'batch_audit': []
        }

        try:
            # Optimized batch loading with relationships
            enrollments = (
                db.session.query(StudentEnrollment)
                .filter(StudentEnrollment.id.in_(enrollment_ids))
                .all()
            )

            for enrollment in enrollments:
                try:
                    # Skip already enrolled (should be filtered earlier but double-check)
                    if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
                        batch_result['skipped'] += 1
                        batch_result['skipped_enrollments'].append({
                            'enrollment_id': enrollment.id,
                            'application_number': enrollment.application_number,
                            'reason': 'Already enrolled as participant'
                        })
                        continue

                    # Determine if this is an override operation
                    is_override = False
                    override_reasons = []

                    if not enrollment.email_verified:
                        is_override = True
                        override_reasons.append('email_unverified')

                    if enrollment.payment_status != PaymentStatus.VERIFIED:
                        is_override = True
                        override_reasons.append('payment_unverified')

                    if enrollment.enrollment_status != EnrollmentStatus.PAYMENT_VERIFIED:
                        is_override = True
                        override_reasons.append(f'status_{enrollment.enrollment_status}')

                    # Process enrollment to participant (core business logic)
                    participant = enrollment.enroll_as_participant(
                        classroom=None,  # Auto-assign based on laptop status
                        processed_by_user_id=processed_by_user_id
                    )

                    # Create user account
                    user, password = participant.create_user_account()

                    # Track success
                    participant_data = {
                        'enrollment_id': str(enrollment.id)              ,
                        'application_number': enrollment.application_number,
                        'participant_id': participant.unique_id,
                        'username': user.username,
                        'password': password,
                        'classroom': participant.classroom,
                        'saturday_session': participant.saturday_session.time_slot if participant.saturday_session else None,
                        'sunday_session': participant.sunday_session.time_slot if participant.sunday_session else None,
                        'is_override': is_override,
                        'override_reasons': override_reasons,
                        'processed_at': datetime.now().isoformat()
                    }

                    if is_override:
                        batch_result['override_processed'] += 1
                        batch_result['override_enrollments'].append(participant_data)
                    else:
                        batch_result['processed'] += 1
                        batch_result['created_participants'].append(participant_data)

                    # Track session assignments
                    if participant.saturday_session:
                        time_slot = participant.saturday_session.time_slot
                        batch_result['session_assignments']['Saturday'][time_slot] = \
                            batch_result['session_assignments']['Saturday'].get(time_slot, 0) + 1

                    if participant.sunday_session:
                        time_slot = participant.sunday_session.time_slot
                        batch_result['session_assignments']['Sunday'][time_slot] = \
                            batch_result['session_assignments']['Sunday'].get(time_slot, 0) + 1

                    # Track classroom distribution
                    batch_result['classroom_distribution'][participant.classroom] = \
                        batch_result['classroom_distribution'].get(participant.classroom, 0) + 1

                    # Send enrollment emails if requested
                    if send_emails:
                        try:
                            custom_data = {
                                'participant': {
                                    'unique_id': participant.unique_id,
                                    'username': user.username,
                                    'password': password,
                                    'classroom': participant.classroom,
                                    'is_override_enrollment': is_override
                                }
                            }

                            EnrollmentService.send_enrollment_status_email(
                                enrollment.id, 'approved', custom_data
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to send approval email for {enrollment.application_number}: {e}")

                    # Audit logging for overrides
                    if is_override:
                        batch_result['batch_audit'].append({
                            'enrollment_id': enrollment.id,
                            'application_number': enrollment.application_number,
                            'action': 'override_enrollment',
                            'override_reasons': override_reasons,
                            'processed_by': processed_by_user_id,
                            'timestamp': datetime.now().isoformat()
                        })

                except Exception as e:
                    batch_result['failed'] += 1
                    batch_result['failed_enrollments'].append({
                        'enrollment_id': enrollment.id,
                        'application_number': enrollment.application_number,
                        'error': str(e),
                        'failed_at': datetime.now().isoformat()
                    })
                    logger.error(f"Failed to process enrollment {enrollment.application_number}: {e}")

            return batch_result

        except Exception as e:
            logger.error(f"Optimized batch processing failed: {str(e)}")
            raise

    @staticmethod
    def _generate_bulk_analysis_optimized(base_query, mode: str, constraints: Optional[Dict]) -> Dict[str, Any]:
        """Generate analysis using database aggregation for performance."""

        # Use database aggregation instead of Python loops
        analysis_query = db.session.query(
            func.count(StudentEnrollment.id).label('total_candidates'),
            func.sum(case((StudentEnrollment.email_verified == True, 1), else_=0)).label('email_verified'),
            func.sum(case((StudentEnrollment.payment_status == PaymentStatus.VERIFIED, 1), else_=0)).label(
                'payment_verified'),
            func.sum(case((StudentEnrollment.has_laptop == True, 1), else_=0)).label('has_laptop'),
            func.sum(case((
                and_(
                    StudentEnrollment.email_verified == True,
                    StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                    StudentEnrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED
                ), 1), else_=0)).label('ready_for_enrollment')
        )

        result = analysis_query.one()

        return {
            'total_candidates': result.total_candidates or 0,
            'email_verified': result.email_verified or 0,
            'payment_verified': result.payment_verified or 0,
            'has_laptop': result.has_laptop or 0,
            'ready_for_enrollment': result.ready_for_enrollment or 0,
            'processing_mode': mode,
            'constraints_impact': constraints is not None
        }

    @staticmethod
    def _analyze_bulk_capacity_impact_optimized(enrollments) -> Dict[str, Any]:
        """Optimized capacity impact analysis."""
        laptop_count = sum(1 for e in enrollments if e.has_laptop)
        no_laptop_count = len(enrollments) - laptop_count

        return {
            'total_impact': len(enrollments),
            'laptop_classroom_impact': laptop_count,
            'no_laptop_classroom_impact': no_laptop_count,
            'estimated_session_load': {
                'Saturday': len(enrollments),
                'Sunday': len(enrollments)
            }
        }

    @staticmethod
    def _analyze_constraint_overrides(enrollments) -> List[Dict[str, Any]]:
        """Analyze constraint violations for override mode."""
        warnings = []

        for enrollment in enrollments:
            violations = []

            if not enrollment.email_verified:
                violations.append('Email not verified')

            if enrollment.payment_status != PaymentStatus.VERIFIED:
                violations.append('Payment not admin-verified')

            if enrollment.enrollment_status not in [EnrollmentStatus.PAYMENT_VERIFIED]:
                violations.append(f'Status: {enrollment.enrollment_status}')

            if violations:
                warnings.append({
                    'application_number': enrollment.application_number,
                    'violations': violations,
                    'severity': 'high' if 'Payment not admin-verified' in violations else 'medium'
                })

        return warnings

    @staticmethod
    def _merge_batch_results(overall_results: Dict, batch_result: Dict):
        """Merge batch results into overall results efficiently."""
        # Numeric aggregations
        overall_results['processed'] += batch_result['processed']
        overall_results['failed'] += batch_result['failed']
        overall_results['skipped'] += batch_result['skipped']
        overall_results['override_processed'] += batch_result.get('override_processed', 0)

        # List extensions
        overall_results['created_participants'].extend(batch_result['created_participants'])
        overall_results['failed_enrollments'].extend(batch_result['failed_enrollments'])
        overall_results['skipped_enrollments'].extend(batch_result['skipped_enrollments'])
        overall_results['override_enrollments'].extend(batch_result.get('override_enrollments', []))

        # Session assignment merging
        for day in ['Saturday', 'Sunday']:
            for time_slot, count in batch_result['session_assignments'][day].items():
                overall_results['session_assignments'][day][time_slot] = \
                    overall_results['session_assignments'][day].get(time_slot, 0) + count

        # Classroom distribution merging
        for classroom, count in batch_result['classroom_distribution'].items():
            overall_results['classroom_distribution'][classroom] = \
                overall_results['classroom_distribution'].get(classroom, 0) + count

        # Audit trail extension
        overall_results['audit_trail'].extend(batch_result.get('batch_audit', []))
        overall_results['batch_results'].append(batch_result)

    @staticmethod
    def _audit_bulk_enrollment_operation(results: Dict, processed_by_user_id: Optional[str]):
        """Enhanced audit logging for bulk enrollment operations."""
        logger = logging.getLogger('enrollment_audit')

        audit_entry = {
            'operation': 'bulk_enrollment',
            'processed_by': processed_by_user_id,
            'timestamp': datetime.now().isoformat(),
            'processing_mode': results['processing_mode'],
            'force_override_used': results.get('force_override_used', False),
            'summary': {
                'total_requested': results['total_requested'],
                'successfully_processed': results['processed'],
                'override_processed': results.get('override_processed', 0),
                'failed': results['failed'],
                'skipped': results['skipped']
            },
            'constraints_applied': results.get('constraints_applied', {}),
            'override_details': results.get('override_enrollments', []),
            'session_impact': results['session_assignments'],
            'classroom_impact': results['classroom_distribution']
        }

        # Log comprehensive audit entry
        logger.info(f"Bulk enrollment audit: {audit_entry}")

        # Store audit trail in results for API response
        results['comprehensive_audit'] = audit_entry
