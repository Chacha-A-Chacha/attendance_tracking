# routes/enrollment.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from ...services.enrollment_service import EnrollmentService
from ...models.enrollment import EnrollmentStatus, PaymentStatus
from .forms import EnrollmentForm, EditEnrollmentForm, ReceiptUpdateForm, SearchApplicationForm, EmailVerificationForm
import os
from datetime import datetime

from . import enrollment_bp


@enrollment_bp.route('/', methods=['GET', 'POST'])
def create_enrollment():
    """Create new enrollment application."""
    form = EnrollmentForm()

    if form.validate_on_submit():
        try:
            # Extract form data
            personal_info = {
                'surname': form.surname.data.strip(),
                'first_name': form.first_name.data.strip(),
                'second_name': form.second_name.data.strip() if form.second_name.data else None
            }

            contact_info = {
                'email': form.email.data.strip().lower(),
                'phone': form.phone.data.strip()
            }

            learning_resources_info = {
                'has_laptop': form.has_laptop.data == 'yes',
                'laptop_brand': form.laptop_brand.data.strip() if form.laptop_brand.data else None,
                'laptop_model': form.laptop_model.data.strip() if form.laptop_model.data else None,
                'needs_laptop_rental': form.needs_laptop_rental.data
            }

            payment_info = {
                'receipt_number': form.receipt_number.data.strip(),
                'payment_amount': float(form.payment_amount.data),
                'receipt_file': form.receipt_file.data
            }

            additional_info = {
                'emergency_contact': form.emergency_contact.data.strip() if form.emergency_contact.data else None,
                'emergency_phone': form.emergency_phone.data.strip() if form.emergency_phone.data else None,
                'special_requirements': form.special_requirements.data.strip() if form.special_requirements.data else None,
                'how_did_you_hear': form.how_did_you_hear.data if form.how_did_you_hear.data else None,
                'previous_attendance': form.previous_attendance.data == 'yes' if form.previous_attendance.data else False
            }

            # Create enrollment with confirmation email
            base_url = request.url_root.rstrip('/')
            enrollment, task_id, token = EnrollmentService.create_enrollment_with_confirmation(
                personal_info, contact_info, learning_resources_info,
                payment_info, additional_info, base_url
            )

            flash(f'Application submitted successfully! Application Number: {enrollment.application_number}', 'success')
            return redirect(url_for('enrollment.enrollment_success', enrollment_id=enrollment.id))

        except ValueError as e:
            flash(str(e), 'error')
        except RequestEntityTooLarge:
            flash('File too large. Please upload a smaller receipt file.', 'error')
        except Exception as e:
            current_app.logger.error(f"Enrollment creation error: {str(e)}")
            flash('An error occurred while processing your application. Please try again.', 'error')

    return render_template('enrollment/create.html',
                           form=form,
                           config=current_app.config,
                           max_file_size=current_app.config['MAX_RECEIPT_SIZE'])


@enrollment_bp.route('/success/<enrollment_id>')
def enrollment_success(enrollment_id):
    """Show enrollment success page."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        return render_template('enrollment/success.html',
                               enrollment=enrollment,
                               verification_sent=True)
    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.create_enrollment'))


@enrollment_bp.route('/search', methods=['GET', 'POST'])
def search_application():
    """Search for application to view dashboard."""
    form = SearchApplicationForm()

    if form.validate_on_submit():
        search_term = form.search_term.data.strip()

        try:
            # Try to find by email first
            enrollment = EnrollmentService.get_enrollment_by_email(search_term)

            # If not found by email, try application number
            if not enrollment:
                enrollment = EnrollmentService.get_enrollment_by_application_number(search_term)

            if not enrollment:
                flash('No application found with that email or application number.', 'error')
                return render_template('enrollment/search.html', form=form)

            # Redirect to application dashboard
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment.id))

        except ValueError as e:
            flash(str(e), 'error')

    return render_template('enrollment/search.html', form=form)


@enrollment_bp.route('/dashboard/<enrollment_id>')
def application_dashboard(enrollment_id):
    """Application dashboard with context-aware action buttons."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        can_edit, edit_info = EnrollmentService.can_edit_enrollment(enrollment_id)

        # Determine available actions based on current state
        available_actions = {
            'can_edit_info': can_edit and isinstance(edit_info, dict) and edit_info.get('info_fields'),
            'can_update_receipt': can_edit and isinstance(edit_info, dict) and edit_info.get('receipt_editable', False),
            'can_resend_verification': not enrollment.email_verified,
            'can_view_receipt': enrollment.receipt_upload_path is not None,
            'can_download_receipt': enrollment.receipt_upload_path is not None,
            'is_completed': enrollment.enrollment_status == EnrollmentStatus.ENROLLED,
            'is_rejected': enrollment.enrollment_status == EnrollmentStatus.REJECTED,
            'is_cancelled': enrollment.enrollment_status == EnrollmentStatus.CANCELLED,
            'needs_verification': not enrollment.email_verified,
            'awaiting_payment_verification': (
                    enrollment.email_verified and
                    enrollment.payment_status == PaymentStatus.PAID and
                    enrollment.enrollment_status == EnrollmentStatus.PAYMENT_PENDING
            ),
            'ready_for_processing': enrollment.is_ready_for_enrollment()
        }

        # Calculate next steps for user
        next_steps = []
        if not enrollment.email_verified:
            next_steps.append({
                'text': 'Verify your email address',
                'action': 'verify_email',
                'priority': 'high',
                'icon': 'envelope'
            })
        elif enrollment.payment_status == PaymentStatus.PAID:
            next_steps.append({
                'text': 'Wait for admin to verify your payment',
                'action': 'wait',
                'priority': 'medium',
                'icon': 'clock'
            })
        elif enrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED:
            next_steps.append({
                'text': 'Wait for enrollment decision',
                'action': 'wait',
                'priority': 'medium',
                'icon': 'hourglass'
            })

        # Status message
        status_message = _get_status_message(enrollment)

        return render_template('enrollment/dashboard.html',
                               enrollment=enrollment,
                               can_edit=can_edit,
                               edit_info=edit_info,
                               actions=available_actions,
                               next_steps=next_steps,
                               status_message=status_message)

    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/edit/<enrollment_id>', methods=['GET', 'POST'])
def edit_enrollment(enrollment_id):
    """Edit enrollment information."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        can_edit, edit_info = EnrollmentService.can_edit_enrollment(enrollment_id)

        if not can_edit:
            flash(f'Cannot edit this application: {edit_info}', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))

    form = EditEnrollmentForm(enrollment=enrollment)

    if request.method == 'GET':
        # Pre-populate form with existing data
        form.phone.data = enrollment.phone
        form.has_laptop.data = 'yes' if enrollment.has_laptop else 'no'
        form.laptop_brand.data = enrollment.laptop_brand
        form.laptop_model.data = enrollment.laptop_model
        form.needs_laptop_rental.data = enrollment.needs_laptop_rental
        form.emergency_contact.data = enrollment.emergency_contact
        form.emergency_phone.data = enrollment.emergency_phone
        form.how_did_you_hear.data = enrollment.how_did_you_hear
        form.previous_attendance.data = 'yes' if enrollment.previous_attendance else 'no'
        form.special_requirements.data = enrollment.special_requirements

    if form.validate_on_submit():
        try:
            # Extract updates from form
            updates = {
                'phone': form.phone.data.strip(),
                'has_laptop': form.has_laptop.data == 'yes',
                'laptop_brand': form.laptop_brand.data.strip() if form.laptop_brand.data else None,
                'laptop_model': form.laptop_model.data.strip() if form.laptop_model.data else None,
                'needs_laptop_rental': form.needs_laptop_rental.data,
                'emergency_contact': form.emergency_contact.data.strip() if form.emergency_contact.data else None,
                'emergency_phone': form.emergency_phone.data.strip() if form.emergency_phone.data else None,
                'special_requirements': form.special_requirements.data.strip() if form.special_requirements.data else None,
                'how_did_you_hear': form.how_did_you_hear.data if form.how_did_you_hear.data else None,
                'previous_attendance': form.previous_attendance.data == 'yes' if form.previous_attendance.data else False
            }

            # Remove empty values to avoid unnecessary updates
            updates = {k: v for k, v in updates.items() if v is not None and v != ''}

            # Update enrollment
            updated_enrollment, changes = EnrollmentService.update_enrollment_info(enrollment_id, updates)

            if changes:
                flash(f'Information updated successfully! {len(changes)} fields changed.', 'success')
            else:
                flash('No changes were made.', 'info')

            return redirect(url_for('enrollment.edit_success', enrollment_id=enrollment_id))

        except ValueError as e:
            flash(str(e), 'error')

    return render_template('enrollment/edit.html',
                           form=form,
                           enrollment=enrollment,
                           edit_info=edit_info,
                           config=current_app.config)


@enrollment_bp.route('/edit/success/<enrollment_id>')
def edit_success(enrollment_id):
    """Show edit success page."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        return render_template('enrollment/edit_success.html', enrollment=enrollment)
    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/update-receipt/<enrollment_id>', methods=['GET', 'POST'])
def update_receipt(enrollment_id):
    """Update receipt information."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        can_edit, edit_info = EnrollmentService.can_edit_enrollment(enrollment_id)

        if not can_edit or not edit_info.get('receipt_editable', False):
            flash('Cannot update receipt for this application.', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))

    form = ReceiptUpdateForm()

    if request.method == 'GET':
        # Pre-populate form with existing data
        form.receipt_number.data = enrollment.receipt_number
        form.payment_amount.data = enrollment.payment_amount

    if form.validate_on_submit():
        try:
            # Update receipt
            updated_enrollment, filename = EnrollmentService.update_receipt(
                enrollment_id,
                form.receipt_file.data,
                form.receipt_number.data.strip(),
                float(form.payment_amount.data)
            )

            flash('Receipt updated successfully! Admin will verify the new payment.', 'success')
            return redirect(url_for('enrollment.receipt_success', enrollment_id=enrollment_id))

        except ValueError as e:
            flash(str(e), 'error')
        except RequestEntityTooLarge:
            flash('File too large. Please upload a smaller receipt file.', 'error')

    return render_template('enrollment/update_receipt.html',
                           form=form,
                           enrollment=enrollment,
                           config=current_app.config)


@enrollment_bp.route('/receipt/success/<enrollment_id>')
def receipt_success(enrollment_id):
    """Show receipt update success page."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        return render_template('enrollment/receipt_success.html', enrollment=enrollment)
    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/verify-email/<enrollment_id>/<token>')
def verify_email(enrollment_id, token):
    """Verify email address."""
    try:
        success = EnrollmentService.verify_email(enrollment_id, token)

        if success:
            enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
            flash('Email verified successfully!', 'success')
            return render_template('enrollment/email_verified.html', enrollment=enrollment)
        else:
            flash('Email verification failed.', 'error')
            return redirect(url_for('enrollment.create_enrollment'))

    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('enrollment.create_enrollment'))


@enrollment_bp.route('/status/<enrollment_id>')
def application_status(enrollment_id):
    """Legacy route - redirect to new dashboard."""
    return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))


@enrollment_bp.route('/resend-verification/<enrollment_id>', methods=['POST'])
def resend_verification(enrollment_id):
    """Resend email verification."""
    form = EmailVerificationForm()
    form.enrollment_id.data = enrollment_id

    if form.validate_on_submit():
        try:
            enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

            if enrollment.email_verified:
                flash('Email is already verified.', 'info')
                return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

            # Send verification email
            base_url = request.url_root.rstrip('/')
            task_id, token = EnrollmentService.send_enrollment_confirmation_email(enrollment_id, base_url)

            flash('Verification email sent! Please check your inbox.', 'success')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

        except ValueError as e:
            flash(str(e), 'error')

    return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/application/<application_number>')
def find_by_application_number(application_number):
    """Find application by application number and redirect to dashboard."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_application_number(application_number)
        return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment.id))
    except ValueError:
        flash('Application not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/download-receipt/<enrollment_id>')
def download_receipt(enrollment_id):
    """Download receipt file."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment.receipt_upload_path:
            flash('No receipt file found for this application.', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

        file_path = EnrollmentService.get_receipt_file_path(enrollment_id)

        if not file_path or not os.path.exists(file_path):
            flash('Receipt file not found on server.', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

        # Get original filename from path
        filename = os.path.basename(file_path)
        # Create a user-friendly filename
        friendly_name = f"receipt_{enrollment.application_number}_{filename.split('_')[-1]}"

        from flask import send_file
        return send_file(file_path, as_attachment=True, download_name=friendly_name)

    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/view-receipt/<enrollment_id>')
def view_receipt(enrollment_id):
    """View receipt in browser."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment.receipt_upload_path:
            flash('No receipt file found for this application.', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

        file_path = EnrollmentService.get_receipt_file_path(enrollment_id)

        if not file_path or not os.path.exists(file_path):
            flash('Receipt file not found on server.', 'error')
            return redirect(url_for('enrollment.application_dashboard', enrollment_id=enrollment_id))

        from flask import send_file
        return send_file(file_path)

    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/summary/<enrollment_id>')
def application_summary(enrollment_id):
    """Show detailed application summary."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        return render_template('enrollment/summary.html', enrollment=enrollment)
    except ValueError:
        flash('Enrollment not found.', 'error')
        return redirect(url_for('enrollment.search_application'))


@enrollment_bp.route('/check-email', methods=['POST'])
def check_email():
    """AJAX endpoint to check if email exists."""
    email = request.json.get('email', '').strip().lower()

    if not email:
        return jsonify({'exists': False, 'message': 'Email is required'})

    try:
        # Check in enrollments
        enrollment = EnrollmentService.get_enrollment_by_email(email)
        if enrollment:
            return jsonify({
                'exists': True,
                'type': 'enrollment',
                'message': f'Email already has application #{enrollment.application_number}',
                'application_number': enrollment.application_number,
                'status': enrollment.enrollment_status
            })

        # Check in participants (assuming similar service exists)
        from models.participant import Participant
        participant = Participant.query.filter_by(email=email).first()
        if participant:
            return jsonify({
                'exists': True,
                'type': 'participant',
                'message': f'Email is already enrolled as participant {participant.unique_id}'
            })

        return jsonify({'exists': False, 'message': 'Email is available'})

    except Exception as e:
        current_app.logger.error(f"Email check error: {str(e)}")
        return jsonify({'exists': False, 'message': 'Could not check email availability'})


# Helper functions
def _get_status_message(enrollment):
    """Get user-friendly status message."""
    if enrollment.enrollment_status == EnrollmentStatus.PENDING:
        if not enrollment.email_verified:
            return {
                'text': 'Please verify your email address to proceed.',
                'type': 'warning',
                'icon': 'envelope'
            }
        else:
            return {
                'text': 'Application submitted. Waiting for payment verification.',
                'type': 'info',
                'icon': 'clock'
            }

    elif enrollment.enrollment_status == EnrollmentStatus.PAYMENT_PENDING:
        if not enrollment.email_verified:
            return {
                'text': 'Please verify your email address.',
                'type': 'warning',
                'icon': 'envelope'
            }
        else:
            return {
                'text': 'Payment received. Waiting for admin verification.',
                'type': 'info',
                'icon': 'hourglass'
            }

    elif enrollment.enrollment_status == EnrollmentStatus.PAYMENT_VERIFIED:
        return {
            'text': 'Payment verified! Waiting for enrollment decision.',
            'type': 'success',
            'icon': 'check-circle'
        }

    elif enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
        return {
            'text': 'Congratulations! You have been enrolled in the course.',
            'type': 'success',
            'icon': 'star'
        }

    elif enrollment.enrollment_status == EnrollmentStatus.REJECTED:
        return {
            'text': 'Application has been rejected. Contact support for details.',
            'type': 'danger',
            'icon': 'x-circle'
        }

    elif enrollment.enrollment_status == EnrollmentStatus.CANCELLED:
        return {
            'text': 'Application has been cancelled.',
            'type': 'secondary',
            'icon': 'slash-circle'
        }

    else:
        return {
            'text': 'Application status unknown.',
            'type': 'secondary',
            'icon': 'question-circle'
        }


# Error handlers specific to enrollment
@enrollment_bp.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    """Handle file upload too large."""
    flash('File too large. Please upload a smaller file.', 'error')
    return redirect(request.url)


@enrollment_bp.errorhandler(413)
def handle_413(e):
    """Handle payload too large."""
    flash('Upload too large. Please try with smaller files.', 'error')
    return redirect(url_for('enrollment.create_enrollment'))


# Template context processors
@enrollment_bp.app_context_processor
def inject_enrollment_helpers():
    """Inject helper functions into templates."""

    def enrollment_status_badge(status):
        """Return CSS class for status badge."""
        status_classes = {
            EnrollmentStatus.PENDING: 'badge-warning',
            EnrollmentStatus.PAYMENT_PENDING: 'badge-info',
            EnrollmentStatus.PAYMENT_VERIFIED: 'badge-primary',
            EnrollmentStatus.ENROLLED: 'badge-success',
            EnrollmentStatus.REJECTED: 'badge-danger',
            EnrollmentStatus.CANCELLED: 'badge-secondary'
        }
        return status_classes.get(status, 'badge-secondary')

    def payment_status_badge(status):
        """Return CSS class for payment status badge."""
        status_classes = {
            PaymentStatus.UNPAID: 'badge-danger',
            PaymentStatus.PAID: 'badge-warning',
            PaymentStatus.VERIFIED: 'badge-success'
        }
        return status_classes.get(status, 'badge-secondary')

    def format_currency(amount):
        """Format currency amount."""
        if amount:
            return f"${amount:,.2f}"
        return "N/A"

    return {
        'enrollment_status_badge': enrollment_status_badge,
        'payment_status_badge': payment_status_badge,
        'format_currency': format_currency,
        'EnrollmentStatus': EnrollmentStatus,
        'PaymentStatus': PaymentStatus
    }


# Utility functions for templates
@enrollment_bp.app_template_filter('enrollment_progress')
def enrollment_progress_filter(enrollment):
    """Calculate enrollment progress percentage."""
    if hasattr(enrollment, 'get_enrollment_progress'):
        return enrollment.get_enrollment_progress()
    return 0


@enrollment_bp.app_template_filter('time_ago')
def time_ago_filter(dt):
    """Show time ago in human readable format."""
    if not dt:
        return "N/A"

    now = datetime.now()
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    else:
        return "Just now"
