# controllers/admin_enrollment.py
"""
Streamlined admin enrollment management routes.
Handles application review, payment verification, approval/rejection with AJAX.
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
    """Main dashboard for all enrollment applications with laptop filtering."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    laptop_filter = request.args.get('laptop', '', type=str)  # 'yes', 'no', or ''

    try:
        # Base query with optimized loading
        query = db.session.query(StudentEnrollment).order_by(StudentEnrollment.submitted_at.desc())

        # Apply search filter
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    StudentEnrollment.application_number.ilike(search_pattern),
                    StudentEnrollment.first_name.ilike(search_pattern),
                    StudentEnrollment.surname.ilike(search_pattern),
                    StudentEnrollment.email.ilike(search_pattern),
                    StudentEnrollment.phone.ilike(search_pattern)
                )
            )

        # Apply laptop filter
        if laptop_filter == 'yes':
            query = query.filter(StudentEnrollment.has_laptop == True)
        elif laptop_filter == 'no':
            query = query.filter(StudentEnrollment.has_laptop == False)

        # Pagination
        total = query.count()
        enrollments = query.offset((page - 1) * per_page).limit(per_page).all()

        # Get dashboard statistics
        stats = EnrollmentService.get_enrollment_statistics()

        # Calculate additional metrics
        dashboard_stats = {
            'total_applications': stats['total'],
            'pending_applications': stats['by_status'].get(EnrollmentStatus.PENDING, 0) +
                                    stats['by_status'].get(EnrollmentStatus.PAYMENT_PENDING, 0),
            'ready_for_processing': stats.get('ready_for_processing', 0),
            'enrolled_count': stats['by_status'].get(EnrollmentStatus.ENROLLED, 0),
            'laptop_count': db.session.query(func.count(StudentEnrollment.id))
            .filter(StudentEnrollment.has_laptop == True).scalar(),
            'no_laptop_count': db.session.query(func.count(StudentEnrollment.id))
            .filter(StudentEnrollment.has_laptop == False).scalar()
        }

        return render_template(
            'admin/enrollment/pending_applications.html',
            enrollments=enrollments,
            stats=dashboard_stats,
            search=search,
            laptop_filter=laptop_filter,
            page=page,
            per_page=per_page,
            total=total,
            has_prev=page > 1,
            has_next=(page * per_page) < total,
            prev_num=page - 1 if page > 1 else None,
            next_num=page + 1 if (page * per_page) < total else None
        )

    except Exception as e:
        flash('Error loading applications.', 'error')
        current_app.logger.error(f"Pending applications error: {str(e)}")
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
            return redirect(url_for('admin.pending_applications'))

        # Get processing timeline
        timeline = []

        timeline.append({
            'date': enrollment.submitted_at,
            'event': 'Application Submitted',
            'description': f'Application {enrollment.application_number} submitted',
            'type': 'info'
        })

        if enrollment.email_verified:
            timeline.append({
                'date': enrollment.email_verification_sent_at,
                'event': 'Email Verified',
                'description': 'Email address verified by applicant',
                'type': 'success'
            })

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

        timeline.sort(key=lambda x: x['date'] if x['date'] else datetime.min)

        # Get available classrooms
        available_classrooms = [
            current_app.config['LAPTOP_CLASSROOM'],
            current_app.config['NO_LAPTOP_CLASSROOM']
        ]

        suggested_classroom = (
            current_app.config['LAPTOP_CLASSROOM'] if enrollment.has_laptop
            else current_app.config['NO_LAPTOP_CLASSROOM']
        )

        return render_template(
            'admin/enrollment/application_detail.html',
            enrollment=enrollment,
            timeline=timeline,
            available_classrooms=available_classrooms,
            suggested_classroom=suggested_classroom
        )

    except Exception as e:
        flash('Error loading application details.', 'error')
        current_app.logger.error(f"Application detail error: {str(e)}")
        return redirect(url_for('admin.pending_applications'))


@admin_bp.route('/analytics')
@login_required
@staff_required
def analytics():
    """Enrollment analytics and reporting dashboard."""
    try:
        stats = EnrollmentService.get_enrollment_statistics()
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

        # Daily enrollments trend (last 30 days)
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

        # Processing time analytics
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


# AJAX Endpoints

@admin_bp.route('/search', methods=['POST'])
@login_required
@staff_required
def search_applications():
    """AJAX endpoint for application search."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    search_term = data.get('search', '').strip()
    laptop_filter = data.get('laptop', '')
    limit = data.get('limit', 10)

    if not search_term and not laptop_filter:
        return jsonify({'applications': []})

    try:
        query = db.session.query(StudentEnrollment)

        # Apply search filter
        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                or_(
                    StudentEnrollment.application_number.ilike(search_pattern),
                    StudentEnrollment.first_name.ilike(search_pattern),
                    StudentEnrollment.surname.ilike(search_pattern),
                    StudentEnrollment.email.ilike(search_pattern),
                    StudentEnrollment.phone.ilike(search_pattern)
                )
            )

        # Apply laptop filter
        if laptop_filter == 'yes':
            query = query.filter(StudentEnrollment.has_laptop == True)
        elif laptop_filter == 'no':
            query = query.filter(StudentEnrollment.has_laptop == False)

        enrollments = query.order_by(StudentEnrollment.submitted_at.desc()).limit(limit).all()

        applications_data = []
        for enrollment in enrollments:
            applications_data.append({
                'id': enrollment.id,
                'application_number': enrollment.application_number,
                'full_name': enrollment.full_name,
                'email': enrollment.email,
                'phone': enrollment.phone,
                'enrollment_status': enrollment.enrollment_status.value,
                'payment_status': enrollment.payment_status.value,
                'email_verified': enrollment.email_verified,
                'submitted_at': enrollment.submitted_at.isoformat() if enrollment.submitted_at else None,
                'has_laptop': enrollment.has_laptop,
                'is_ready_for_enrollment': enrollment.is_ready_for_enrollment()
            })

        return jsonify({'applications': applications_data})

    except Exception as e:
        current_app.logger.error(f"Search error: {str(e)}")
        return jsonify({'error': 'Search failed'}), 500


@admin_bp.route('/<enrollment_id>/approve', methods=['POST'])
@login_required
@staff_required
def approve_application(enrollment_id):
    """AJAX endpoint for application approval."""
    try:
        data = request.get_json()
        classroom = data.get('classroom')
        admin_notes = data.get('admin_notes', '').strip()

        if not classroom:
            return jsonify({
                'success': False,
                'message': 'Please select a classroom for the participant.'
            }), 400

        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            return jsonify({
                'success': False,
                'message': 'Enrollment application not found.'
            }), 404

        if not enrollment.is_ready_for_enrollment():
            return jsonify({
                'success': False,
                'message': 'Application is not ready for approval. Email and payment must be verified first.'
            }), 400

        participant, enrollment = EnrollmentService.process_enrollment_to_participant(
            enrollment_id, classroom, current_user.id
        )

        return jsonify({
            'success': True,
            'message': f'Application approved! Participant {participant.unique_id} created successfully.',
            'participant_id': participant.unique_id,
            'new_status': enrollment.enrollment_status.value
        })

    except Exception as e:
        current_app.logger.error(f"Application approval error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error approving application.'
        }), 500


@admin_bp.route('/<enrollment_id>/reject', methods=['POST'])
@login_required
@staff_required
def reject_application(enrollment_id):
    """AJAX endpoint for application rejection."""
    try:
        data = request.get_json()
        reason = data.get('reason', '').strip()
        admin_notes = data.get('admin_notes', '').strip()

        if not reason:
            return jsonify({
                'success': False,
                'message': 'Please provide a reason for rejection.'
            }), 400

        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            return jsonify({
                'success': False,
                'message': 'Enrollment application not found.'
            }), 404

        if enrollment.enrollment_status == EnrollmentStatus.ENROLLED:
            return jsonify({
                'success': False,
                'message': 'Cannot reject - application is already enrolled as participant.'
            }), 400

        EnrollmentService.reject_enrollment(enrollment_id, reason, current_user.id)

        return jsonify({
            'success': True,
            'message': f'Application {enrollment.application_number} has been rejected.',
            'new_status': EnrollmentStatus.REJECTED.value
        })

    except Exception as e:
        current_app.logger.error(f"Application rejection error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error rejecting application.'
        }), 500


@admin_bp.route('/<enrollment_id>/verify-payment', methods=['POST'])
@login_required
@staff_required
def verify_payment(enrollment_id):
    """AJAX endpoint for payment verification."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            return jsonify({
                'success': False,
                'message': 'Enrollment application not found.'
            }), 404

        if enrollment.payment_status == PaymentStatus.VERIFIED:
            return jsonify({
                'success': False,
                'message': 'Payment is already verified.'
            }), 400

        EnrollmentService.verify_payment(enrollment_id, current_user.id)

        return jsonify({
            'success': True,
            'message': f'Payment verified for application {enrollment.application_number}.',
            'new_status': PaymentStatus.VERIFIED.value
        })

    except Exception as e:
        current_app.logger.error(f"Payment verification error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error verifying payment.'
        }), 500


@admin_bp.route('/<enrollment_id>/receipt')
@login_required
@staff_required
def view_receipt(enrollment_id):
    """View uploaded receipt file as preview."""
    try:
        print(f"DEBUG: Looking for enrollment_id: {enrollment_id}")
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)
        print(f"DEBUG: Enrollment found: {enrollment is not None}")

        if not enrollment:
            print("DEBUG: Enrollment not found")
            return jsonify({'error': 'Enrollment not found'}), 404

        print(f"DEBUG: Receipt upload path: {enrollment.receipt_upload_path}")
        receipt_path = EnrollmentService.get_receipt_file_path(enrollment_id)
        print(f"DEBUG: Receipt file path: {receipt_path}")
        print(f"DEBUG: File exists: {os.path.exists(receipt_path) if receipt_path else False}")

        if not receipt_path or not os.path.exists(receipt_path):
            print("DEBUG: Receipt file not found")
            return jsonify({'error': 'Receipt file not found'}), 404

        # Determine content type
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
            as_attachment=False,
            download_name=f"receipt_{enrollment.application_number}{file_ext}"
        )

    except Exception as e:
        current_app.logger.error(f"Receipt view error: {str(e)}")
        return jsonify({'error': 'Error loading receipt'}), 500


@admin_bp.route('/<enrollment_id>/resend-verification')
@login_required
@staff_required
def resend_verification_email(enrollment_id):
    """Resend email verification to applicant."""
    try:
        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            return jsonify({
                'success': False,
                'message': 'Enrollment application not found.'
            }), 404

        if enrollment.email_verified:
            return jsonify({
                'success': False,
                'message': 'Email is already verified.'
            }), 400

        task_id, token = EnrollmentService.send_email_verification(
            enrollment_id,
            base_url=current_app.config.get('BASE_URL')
        )

        return jsonify({
            'success': True,
            'message': f'Verification email resent to {enrollment.email}.'
        })

    except Exception as e:
        current_app.logger.error(f"Resend verification error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error resending verification email.'
        }), 500


@admin_bp.route('/bulk-enrollment')
@login_required
@staff_required
def bulk_enrollment():
    """Bulk enrollment management interface."""
    # Minimal version that definitely returns a response
    return render_template(
        'admin/enrollment/bulk_enrollment.html',
        enrollment_stats={'total': 0, 'ready_for_processing': 0},
        candidates_result={'analysis': {'ready_for_enrollment': 0, 'email_verified': 0, 'payment_verified': 0, 'has_laptop': 0}},
        classroom_utilization={},
        default_constraints={}
    )


@admin_bp.route('/bulk-enrollment/preview', methods=['POST'])
@login_required
@staff_required
def bulk_enrollment_preview():
    """AJAX endpoint to preview bulk enrollment candidates based on constraints."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    constraints = {
        'email_verified': data.get('email_verified'),
        'has_laptop': data.get('has_laptop'),
        'payment_status': data.get('payment_status'),
        'enrollment_status': data.get('enrollment_status'),
        'limit': data.get('limit', 200)
    }

    # Remove None values
    constraints = {k: v for k, v in constraints.items() if v is not None}

    try:
        result = EnrollmentService.get_bulk_enrollment_candidates(constraints)

        # Format for JSON response
        response_data = {
            'success': True,
            'total_count': result['total_count'],
            'analysis': result['analysis'],
            'capacity_impact': result['capacity_impact'],
            'constraints_applied': result['constraints_applied'],
            'preview_data': []
        }

        # Add preview data (limited fields for performance)
        for enrollment in result['preview_enrollments'][:50]:  # Limit preview to 50 items
            response_data['preview_data'].append({
                'id': enrollment.id,
                'application_number': enrollment.application_number,
                'full_name': enrollment.full_name,
                'email': enrollment.email,
                'has_laptop': enrollment.has_laptop,
                'email_verified': enrollment.email_verified,
                'payment_status': enrollment.payment_status,
                'enrollment_status': enrollment.enrollment_status,
                'submitted_at': enrollment.submitted_at.isoformat() if enrollment.submitted_at else None,
                'is_ready': enrollment.is_ready_for_enrollment()
            })

        return jsonify(response_data)

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment preview error: {str(e)}")
        return jsonify({'error': 'Preview failed'}), 500


@admin_bp.route('/bulk-enrollment/process', methods=['POST'])
@login_required
@staff_required
def process_bulk_enrollment():
    """Process bulk enrollment of selected applications."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    enrollment_ids = data.get('enrollment_ids', [])
    constraints = data.get('constraints', {})
    send_emails = data.get('send_emails', True)
    batch_size = data.get('batch_size', 25)

    if not enrollment_ids:
        return jsonify({'error': 'No enrollments selected'}), 400

    if len(enrollment_ids) > 500:
        return jsonify({'error': 'Too many enrollments selected (max 500)'}), 400

    try:
        # Start bulk processing
        results = EnrollmentService.bulk_process_enrollments(
            enrollment_ids=enrollment_ids,
            constraints=constraints,
            processed_by_user_id=current_user.id,
            send_emails=send_emails,
            batch_size=batch_size
        )

        # Format response
        response = {
            'success': True,
            'message': f'Bulk enrollment completed: {results["processed"]} participants created',
            'results': {
                'total_requested': results['total_requested'],
                'processed': results['processed'],
                'failed': results['failed'],
                'skipped': results['skipped'],
                'duration': results['duration'],
                'session_assignments': results['session_assignments'],
                'classroom_distribution': results['classroom_distribution']
            },
            'details': {
                'created_participants': results['created_participants'][:20],  # Limit for response size
                'failed_enrollments': results['failed_enrollments'],
                'skipped_enrollments': results['skipped_enrollments']
            }
        }

        return jsonify(response)

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment processing error: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/bulk-enrollment/progress/<task_id>')
@login_required
@staff_required
def bulk_enrollment_progress(task_id):
    """Get progress of bulk enrollment processing (for future async implementation)."""
    # This is a placeholder for async bulk processing
    # Currently bulk processing is synchronous
    return jsonify({
        'status': 'completed',
        'progress': 100,
        'message': 'Bulk processing completed'
    })


@admin_bp.route('/bulk-enrollment/export-results', methods=['POST'])
@login_required
@staff_required
def export_bulk_enrollment_results():
    """Export bulk enrollment results as CSV."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    results_data = data.get('results')

    if not results_data:
        return jsonify({'error': 'No results data provided'}), 400

    try:
        import csv
        import io
        from flask import make_response

        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Write headers
        writer.writerow([
            'Application Number', 'Participant ID', 'Full Name', 'Email',
            'Username', 'Password', 'Classroom', 'Saturday Session', 'Sunday Session',
            'Status'
        ])

        # Write successful enrollments
        for participant in results_data.get('created_participants', []):
            writer.writerow([
                participant['application_number'],
                participant['participant_id'],
                '',  # Full name would need to be added
                '',  # Email would need to be added
                participant['username'],
                participant['password'],
                participant['classroom'],
                participant['saturday_session'],
                participant['sunday_session'],
                'Successfully Created'
            ])

        # Write failed enrollments
        for failed in results_data.get('failed_enrollments', []):
            writer.writerow([
                failed['application_number'],
                '',
                '',
                '',
                '',
                '',
                '',
                '',
                '',
                f"Failed: {failed['error']}"
            ])

        # Create response
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers[
            'Content-Disposition'] = f'attachment; filename=bulk_enrollment_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

        return response

    except Exception as e:
        current_app.logger.error(f"Export results error: {str(e)}")
        return jsonify({'error': 'Export failed'}), 500
