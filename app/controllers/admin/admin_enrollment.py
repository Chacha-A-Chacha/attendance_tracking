# controllers/admin_enrollment.py
"""
Admin enrollment management routes for processing student applications.
Handles application review, payment verification, approval/rejection, and enrollment analytics.
"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, desc
from datetime import datetime, timedelta
from werkzeug.exceptions import NotFound

from app.models.enrollment import StudentEnrollment, EnrollmentStatus, PaymentStatus
from app.models.participant import Participant
from app.models.user import Permission
from app.services.enrollment_service import EnrollmentService
from app.utils.auth import permission_required, staff_required
from app.extensions import db
from app.config import Config

from . import admin_bp


@admin_bp.route('/pending')
@login_required
@staff_required
def pending_applications():
    """Dashboard for pending enrollment applications."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    email_status = request.args.get('email_status', '', type=str)
    payment_status = request.args.get('payment_status', '', type=str)
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    try:
        # Get pending enrollments with filters
        filters = {}
        if email_status == 'verified':
            filters['verified_only'] = True
        elif email_status == 'unverified':
            filters['verified_only'] = False

        if payment_status:
            filters['payment_status'] = payment_status

        # Get enrollments that are pending or payment-related
        enrollments = EnrollmentService.get_enrollments_for_admin(
            status=EnrollmentStatus.PENDING,
            limit=per_page,
            offset=(page - 1) * per_page
        )

        # Also get payment verified ones ready for processing
        ready_enrollments = EnrollmentService.get_enrollments_for_admin(
            ready_for_processing=True,
            limit=10  # Just show top 10 ready ones
        )

        # Get statistics for dashboard cards
        stats = EnrollmentService.get_enrollment_statistics()

        # Calculate additional metrics
        pending_count = stats['by_status'].get(EnrollmentStatus.PAYMENT_PENDING, 0)
        ready_count = stats.get('ready_for_processing', 0)
        unverified_email_count = (
            db.session.query(func.count(StudentEnrollment.id))
            .filter(
                and_(
                    StudentEnrollment.email_verified == False,
                    StudentEnrollment.enrollment_status.in_([
                        EnrollmentStatus.PENDING,
                        EnrollmentStatus.PAYMENT_PENDING
                    ])
                )
            ).scalar()
        )

        dashboard_stats = {
            'pending_applications': pending_count,
            'ready_for_processing': ready_count,
            'unverified_emails': unverified_email_count,
            'recent_submissions': stats.get('recent_submissions', 0)
        }

        return render_template(
            'admin/enrollment/pending_applications.html',
            enrollments=enrollments,
            ready_enrollments=ready_enrollments,
            stats=dashboard_stats,
            search=search,
            email_status=email_status,
            payment_status=payment_status,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        flash('Error loading pending applications.', 'error')
        current_app.logger.error(f"Pending applications error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/payment-verification')
@login_required
@staff_required
def payment_verification():
    """Payment verification center for reviewing uploaded receipts."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    search = request.args.get('search', '', type=str)
    amount_filter = request.args.get('amount', '', type=str)

    try:
        # Get enrollments with uploaded receipts needing verification
        enrollments = EnrollmentService.get_enrollments_for_admin(
            payment_status=PaymentStatus.PAID,  # Has receipt but not verified
            limit=per_page,
            offset=(page - 1) * per_page
        )

        # Apply search if provided
        if search:
            search_results = EnrollmentService.search_enrollments(search, limit=per_page)
            # Filter to only those needing payment verification
            enrollments = [e for e in search_results if e.payment_status == PaymentStatus.PAID]

        # Get payment verification statistics
        payment_stats = {
            'pending_verification': db.session.query(func.count(StudentEnrollment.id))
            .filter(StudentEnrollment.payment_status == PaymentStatus.PAID).scalar(),
            'verified_today': db.session.query(func.count(StudentEnrollment.id))
            .filter(
                and_(
                    StudentEnrollment.payment_status == PaymentStatus.VERIFIED,
                    func.date(StudentEnrollment.payment_verified_at) == datetime.now().date()
                )
            ).scalar(),
            'total_amount_pending': db.session.query(func.sum(StudentEnrollment.payment_amount))
                                    .filter(StudentEnrollment.payment_status == PaymentStatus.PAID).scalar() or 0
        }

        return render_template(
            'admin/enrollment/payment_verification.html',
            enrollments=enrollments,
            stats=payment_stats,
            search=search,
            amount_filter=amount_filter,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        flash('Error loading payment verification page.', 'error')
        current_app.logger.error(f"Payment verification error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/application-history')
@login_required
@staff_required
def application_history():
    """Complete history of all enrollment applications."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '', type=str)
    status_filter = request.args.get('status', '', type=str)
    payment_filter = request.args.get('payment', '', type=str)
    date_from = request.args.get('date_from', '', type=str)
    date_to = request.args.get('date_to', '', type=str)

    try:
        # Build filters
        filters = {}
        if status_filter:
            filters['status'] = status_filter
        if payment_filter:
            filters['payment_status'] = payment_filter

        # Get all enrollments with filters
        enrollments = EnrollmentService.get_enrollments_for_admin(
            **filters,
            limit=per_page,
            offset=(page - 1) * per_page
        )

        # Apply search if provided
        if search:
            enrollments = EnrollmentService.search_enrollments(search, limit=per_page)

        # Get comprehensive statistics
        all_stats = EnrollmentService.get_enrollment_statistics()

        return render_template(
            'admin/enrollment/application_history.html',
            enrollments=enrollments,
            stats=all_stats,
            search=search,
            status_filter=status_filter,
            payment_filter=payment_filter,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        flash('Error loading application history.', 'error')
        current_app.logger.error(f"Application history error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/analytics')
@login_required
@staff_required
def analytics():
    """Enrollment analytics and reporting dashboard."""
    try:
        # Get comprehensive statistics
        stats = EnrollmentService.get_enrollment_statistics()

        # Calculate additional analytics
        total_enrollments = stats['total']

        # Conversion rates
        if total_enrollments > 0:
            email_verification_rate = (
                    db.session.query(func.count(StudentEnrollment.id))
                    .filter(StudentEnrollment.email_verified == True).scalar() / total_enrollments * 100
            )

            payment_completion_rate = (
                    stats['by_payment_status'].get(PaymentStatus.VERIFIED, 0) / total_enrollments * 100
            )

            enrollment_completion_rate = (
                    stats['by_status'].get(EnrollmentStatus.ENROLLED, 0) / total_enrollments * 100
            )
        else:
            email_verification_rate = 0
            payment_completion_rate = 0
            enrollment_completion_rate = 0

        # Get enrollment trends (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        daily_enrollments = (
            db.session.query(
                func.date(StudentEnrollment.submitted_at).label('date'),
                func.count(StudentEnrollment.id).label('count')
            )
            .filter(StudentEnrollment.submitted_at >= thirty_days_ago)
            .group_by(func.date(StudentEnrollment.submitted_at))
            .order_by('date')
            .all()
        )

        # Get processing time analytics
        avg_processing_time = (
            db.session.query(
                func.avg(
                    func.julianday(StudentEnrollment.processed_at) -
                    func.julianday(StudentEnrollment.submitted_at)
                )
            )
            .filter(StudentEnrollment.processed_at.isnot(None))
            .scalar()
        )

        analytics_data = {
            'total_stats': stats,
            'conversion_rates': {
                'email_verification': round(email_verification_rate, 1),
                'payment_completion': round(payment_completion_rate, 1),
                'enrollment_completion': round(enrollment_completion_rate, 1)
            },
            'trends': {
                'daily_enrollments': [
                    {'date': day.date.strftime('%Y-%m-%d'), 'count': day.count}
                    for day in daily_enrollments
                ]
            },
            'processing': {
                'avg_processing_days': round(avg_processing_time or 0, 1)
            }
        }

        return render_template(
            'admin/enrollment/analytics.html',
            analytics=analytics_data
        )

    except Exception as e:
        flash('Error loading analytics.', 'error')
        current_app.logger.error(f"Analytics error: {str(e)}")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/<enrollment_id>')
@login_required
@staff_required
def application_detail(enrollment_id):
    """Detailed view of a specific enrollment application."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            flash('Enrollment application not found.', 'error')
            return redirect(url_for('admin_enrollment.pending_applications'))

        # Get processing timeline/history
        timeline = []

        # Add submission
        timeline.append({
            'date': enrollment.submitted_at,
            'event': 'Application Submitted',
            'description': f'Application {enrollment.application_number} submitted',
            'type': 'info'
        })

        # Add email verification
        if enrollment.email_verified:
            timeline.append({
                'date': enrollment.email_verification_sent_at,  # Approximate
                'event': 'Email Verified',
                'description': 'Email address verified by applicant',
                'type': 'success'
            })

        # Add payment events
        if enrollment.payment_date:
            timeline.append({
                'date': enrollment.payment_date,
                'event': 'Payment Received',
                'description': f'Payment receipt uploaded (Receipt: {enrollment.receipt_number})',
                'type': 'info'
            })

        if enrollment.payment_verified_at:
            timeline.append({
                'date': enrollment.payment_verified_at,
                'event': 'Payment Verified',
                'description': 'Payment verified by admin',
                'type': 'success'
            })

        # Add processing events
        if enrollment.processed_at:
            if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
                timeline.append({
                    'date': enrollment.processed_at,
                    'event': 'Application Approved',
                    'description': 'Application approved and participant created',
                    'type': 'success'
                })
            elif enrollment.enrollment_status == EnrollmentStatus.REJECTED:
                timeline.append({
                    'date': enrollment.processed_at,
                    'event': 'Application Rejected',
                    'description': f'Application rejected: {enrollment.rejection_reason}',
                    'type': 'error'
                })

        # Sort timeline by date
        timeline.sort(key=lambda x: x['date'] if x['date'] else datetime.min)

        return render_template(
            'admin/enrollment/application_detail.html',
            enrollment=enrollment,
            timeline=timeline
        )

    except Exception as e:
        flash('Error loading application details.', 'error')
        current_app.logger.error(f"Application detail error: {str(e)}")
        return redirect(url_for('admin_enrollment.pending_applications'))


@admin_bp.route('/<enrollment_id>/verify-payment', methods=['GET', 'POST'])
@login_required
@staff_required
def verify_payment(enrollment_id):
    """Verify payment for an enrollment application."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            flash('Enrollment application not found.', 'error')
            return redirect(url_for('admin_enrollment.payment_verification'))

        if enrollment.payment_status == PaymentStatus.VERIFIED:
            flash('Payment is already verified.', 'info')
            return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

        if request.method == 'POST':
            action = request.form.get('action')
            admin_notes = request.form.get('admin_notes', '').strip()

            if action == 'verify':
                try:
                    EnrollmentService.verify_payment(enrollment_id, current_user.id)
                    flash(f'Payment verified for application {enrollment.application_number}.', 'success')
                    return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

                except Exception as e:
                    flash('Error verifying payment.', 'error')
                    current_app.logger.error(f"Payment verification error: {str(e)}")

            elif action == 'reject':
                # Note: You might want to add a reject_payment method to the service
                flash('Payment rejection functionality not yet implemented.', 'warning')

        return render_template(
            'admin/enrollment/verify_payment.html',
            enrollment=enrollment
        )

    except Exception as e:
        flash('Error processing payment verification.', 'error')
        current_app.logger.error(f"Payment verification error: {str(e)}")
        return redirect(url_for('admin_enrollment.payment_verification'))


@admin_bp.route('/<enrollment_id>/approve', methods=['GET', 'POST'])
@login_required
@staff_required
def approve_application(enrollment_id):
    """Approve enrollment application and create participant."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            flash('Enrollment application not found.', 'error')
            return redirect(url_for('admin_enrollment.pending_applications'))

        if not enrollment.is_ready_for_enrollment():
            flash('Application is not ready for approval. Email and payment must be verified first.', 'warning')
            return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

        if request.method == 'POST':
            classroom = request.form.get('classroom')
            admin_notes = request.form.get('admin_notes', '').strip()

            if not classroom:
                flash('Please select a classroom for the participant.', 'error')
                return render_template(
                    'admin/enrollment/approve_application.html',
                    enrollment=enrollment
                )

            try:
                participant, enrollment = EnrollmentService.process_enrollment_to_participant(
                    enrollment_id, classroom, current_user.id
                )

                flash(f'Application approved! Participant {participant.unique_id} created successfully.', 'success')
                flash('Welcome email with login credentials has been sent to the participant.', 'info')

                return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

            except Exception as e:
                flash('Error approving application.', 'error')
                current_app.logger.error(f"Application approval error: {str(e)}")

        # Get available classrooms for selection
        available_classrooms = [
            current_app.config['LAPTOP_CLASSROOM'],
            current_app.config['NO_LAPTOP_CLASSROOM']
        ]

        # Suggest classroom based on laptop status
        suggested_classroom = (
            current_app.config['LAPTOP_CLASSROOM'] if enrollment.has_laptop
            else current_app.config['NO_LAPTOP_CLASSROOM']
        )

        return render_template(
            'admin/enrollment/approve_application.html',
            enrollment=enrollment,
            available_classrooms=available_classrooms,
            suggested_classroom=suggested_classroom
        )

    except Exception as e:
        flash('Error processing application approval.', 'error')
        current_app.logger.error(f"Application approval error: {str(e)}")
        return redirect(url_for('admin_enrollment.pending_applications'))


@admin_bp.route('/<enrollment_id>/reject', methods=['GET', 'POST'])
@login_required
@staff_required
def reject_application(enrollment_id):
    """Reject enrollment application with reason."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            flash('Enrollment application not found.', 'error')
            return redirect(url_for('admin_enrollment.pending_applications'))

        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            flash('Cannot reject - application is already enrolled as participant.', 'error')
            return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

        if request.method == 'POST':
            reason = request.form.get('reason', '').strip()
            admin_notes = request.form.get('admin_notes', '').strip()

            if not reason:
                flash('Please provide a reason for rejection.', 'error')
                return render_template(
                    'admin/enrollment/reject_application.html',
                    enrollment=enrollment
                )

            try:
                EnrollmentService.reject_enrollment(enrollment_id, reason, current_user.id)

                flash(f'Application {enrollment.application_number} has been rejected.', 'success')
                flash('Rejection notification email has been sent to the applicant.', 'info')

                return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

            except Exception as e:
                flash('Error rejecting application.', 'error')
                current_app.logger.error(f"Application rejection error: {str(e)}")

        # Common rejection reasons for quick selection
        common_reasons = [
            'Incomplete payment information',
            'Invalid payment receipt',
            'Duplicate application',
            'Does not meet eligibility criteria',
            'Course capacity reached',
            'Incorrect personal information'
        ]

        return render_template(
            'admin/enrollment/reject_application.html',
            enrollment=enrollment,
            common_reasons=common_reasons
        )

    except Exception as e:
        flash('Error processing application rejection.', 'error')
        current_app.logger.error(f"Application rejection error: {str(e)}")
        return redirect(url_for('admin_enrollment.pending_applications'))


@admin_bp.route('/<enrollment_id>/resend-verification')
@login_required
@staff_required
def resend_verification_email(enrollment_id):
    """Resend email verification to applicant."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            flash('Enrollment application not found.', 'error')
            return redirect(url_for('admin_enrollment.pending_applications'))

        if enrollment.email_verified:
            flash('Email is already verified.', 'info')
            return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

        # Resend verification email
        task_id, token = EnrollmentService.send_email_verification(
            enrollment_id,
            base_url=current_app.config.get('BASE_URL')
        )

        flash(f'Verification email resent to {enrollment.email}.', 'success')

        return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))

    except Exception as e:
        flash('Error resending verification email.', 'error')
        current_app.logger.error(f"Resend verification error: {str(e)}")
        return redirect(url_for('admin_enrollment.application_detail', enrollment_id=enrollment_id))


@admin_bp.route('/<enrollment_id>/receipt')
@login_required
@staff_required
def view_receipt(enrollment_id):
    """View uploaded receipt file as preview."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            return jsonify({'error': 'Enrollment not found'}), 404

        receipt_path = EnrollmentService.get_receipt_file_path(enrollment_id)

        if not receipt_path or not os.path.exists(receipt_path):
            return jsonify({'error': 'Receipt file not found'}), 404

        # Determine content type based on file extension
        file_ext = os.path.splitext(receipt_path)[1].lower()
        content_type_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.pdf': 'application/pdf',
            '.webp': 'image/webp'
        }

        content_type = content_type_map.get(file_ext, 'application/octet-stream')

        return send_file(
            receipt_path,
            mimetype=content_type,
            as_attachment=False,  # Display inline for preview
            download_name=f"receipt_{enrollment.application_number}{file_ext}"
        )

    except Exception as e:
        current_app.logger.error(f"Receipt view error: {str(e)}")
        return jsonify({'error': 'Error loading receipt'}), 500


# AJAX Endpoints for better UX

@admin_bp.route('/search', methods=['POST'])
@login_required
@staff_required
def search_applications():
    """AJAX endpoint for application search."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    search_term = data.get('search', '').strip()
    limit = data.get('limit', 10)

    if not search_term:
        return jsonify({'applications': []})

    try:
        enrollments = EnrollmentService.search_enrollments(search_term, limit=limit)

        applications_data = []
        for enrollment in enrollments:
            applications_data.append({
                'id': enrollment.id,
                'application_number': enrollment.application_number,
                'full_name': enrollment.full_name,
                'email': enrollment.email,
                'phone': enrollment.phone,
                'enrollment_status': enrollment.enrollment_status,
                'payment_status': enrollment.payment_status,
                'email_verified': enrollment.email_verified,
                'submitted_at': enrollment.submitted_at.isoformat() if enrollment.submitted_at else None,
                'has_laptop': enrollment.has_laptop
            })

        return jsonify({'applications': applications_data})

    except Exception as e:
        current_app.logger.error(f"Search error: {str(e)}")
        return jsonify({'error': 'Search failed'}), 500


@admin_bp.route('/<enrollment_id>/quick-verify-payment', methods=['POST'])
@login_required
@staff_required
def quick_verify_payment(enrollment_id):
    """AJAX endpoint for quick payment verification."""
    try:
        enrollment = EnrollmentService.verify_payment(enrollment_id, current_user.id)

        return jsonify({
            'success': True,
            'message': f'Payment verified for application {enrollment.application_number}',
            'new_status': enrollment.payment_status
        })

    except Exception as e:
        current_app.logger.error(f"Quick payment verification error: {str(e)}")
        return jsonify({'success': False, 'message': 'Verification failed'}), 500


@admin_bp.route('/<enrollment_id>/quick-approve', methods=['POST'])
@login_required
@staff_required
def quick_approve_application(enrollment_id):
    """AJAX endpoint for quick application approval."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    classroom = data.get('classroom')

    if not classroom:
        return jsonify({'error': 'Classroom is required'}), 400

    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment.is_ready_for_enrollment():
            return jsonify({'error': 'Application not ready for approval'}), 400

        participant, enrollment = EnrollmentService.process_enrollment_to_participant(
            enrollment_id, classroom, current_user.id
        )

        return jsonify({
            'success': True,
            'message': f'Application approved! Participant {participant.unique_id} created.',
            'participant_id': participant.unique_id,
            'new_status': enrollment.enrollment_status
        })

    except Exception as e:
        current_app.logger.error(f"Quick approval error: {str(e)}")
        return jsonify({'success': False, 'message': 'Approval failed'}), 500


@admin_bp.route('/bulk-action', methods=['POST'])
@login_required
@staff_required
def bulk_action():
    """Handle bulk actions on multiple applications."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    action = data.get('action')
    enrollment_ids = data.get('enrollment_ids', [])

    if not action or not enrollment_ids:
        return jsonify({'error': 'Action and enrollment IDs are required'}), 400

    try:
        results = {'success': 0, 'failed': 0, 'messages': []}

        for enrollment_id in enrollment_ids:
            try:
                if action == 'verify_payments':
                    EnrollmentService.verify_payment(enrollment_id, current_user.id)
                    results['success'] += 1

                elif action == 'resend_verification':
                    EnrollmentService.send_email_verification(enrollment_id)
                    results['success'] += 1

                else:
                    results['failed'] += 1
                    results['messages'].append(f'Unknown action: {action}')

            except Exception as e:
                results['failed'] += 1
                results['messages'].append(f'Failed for {enrollment_id}: {str(e)}')

        return jsonify({
            'success': True,
            'results': results,
            'message': f'Bulk action completed: {results["success"]} succeeded, {results["failed"]} failed'
        })

    except Exception as e:
        current_app.logger.error(f"Bulk action error: {str(e)}")
        return jsonify({'success': False, 'message': 'Bulk action failed'}), 500
