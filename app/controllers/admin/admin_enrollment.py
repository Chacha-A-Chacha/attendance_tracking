# controllers/admin_enrollment.py
"""
Streamlined admin enrollment management routes.
Handles application review, payment verification, approval/rejection with AJAX.
"""
import csv
import io
import os
from typing import List

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, \
    make_response
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, desc
from datetime import datetime, timedelta
from werkzeug.exceptions import NotFound

from app.models.enrollment import StudentEnrollment, EnrollmentStatus, PaymentStatus
from app.models.participant import Participant
from app.models.user import Permission
from app.services.enrollment_service import EnrollmentService, BulkEnrollmentMode
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
    try:
        current_app.logger.info(f"Receipt request for enrollment: {enrollment_id}")

        enrollment = EnrollmentService.get_enrollment_by_id(enrollment_id, include_sensitive=True)

        if not enrollment:
            current_app.logger.error(f"Enrollment not found: {enrollment_id}")
            return "Enrollment not found", 404

        current_app.logger.info(f"Enrollment found. Receipt path from DB: {enrollment.receipt_upload_path}")

        if not enrollment.receipt_upload_path:
            current_app.logger.error(f"No receipt path in database for enrollment: {enrollment_id}")
            return "No receipt uploaded", 404

        receipt_path = EnrollmentService.get_receipt_file_path(enrollment_id)
        current_app.logger.info(f"Constructed full path: {receipt_path}")

        # Check if file exists
        if not receipt_path:
            current_app.logger.error("get_receipt_file_path returned None")
            return "Error constructing file path", 500

        if not os.path.exists(receipt_path):
            current_app.logger.error(f"File does not exist at: {receipt_path}")

            # Check if directory exists
            dir_path = os.path.dirname(receipt_path)
            if os.path.exists(dir_path):
                current_app.logger.info(f"Directory exists: {dir_path}")
                # List files in directory
                try:
                    files = os.listdir(dir_path)
                    current_app.logger.info(f"Files in directory: {files[:10]}")  # Show first 10 files
                except Exception as e:
                    current_app.logger.error(f"Cannot list directory: {e}")
            else:
                current_app.logger.error(f"Directory does not exist: {dir_path}")

            return "Receipt file not found", 404

        # Check file permissions
        try:
            file_size = os.path.getsize(receipt_path)
            current_app.logger.info(f"File exists, size: {file_size} bytes")
        except Exception as e:
            current_app.logger.error(f"Cannot access file: {e}")
            return "Cannot access receipt file", 500

        # Determine content type
        file_ext = os.path.splitext(receipt_path)[1].lower()
        current_app.logger.info(f"File extension: {file_ext}")

        content_type_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.pdf': 'application/pdf',
            '.webp': 'image/webp'
        }

        content_type = content_type_map.get(file_ext, 'application/octet-stream')
        current_app.logger.info(f"Content type: {content_type}")

        return send_file(
            receipt_path,
            mimetype=content_type,
            as_attachment=False,
            download_name=f"receipt_{enrollment.application_number}{file_ext}"
        )

    except Exception as e:
        current_app.logger.error(f"Receipt view error: {str(e)}", exc_info=True)
        return f"Error loading receipt: {str(e)}", 500


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



# Updated Bulk Enrollment Endpoints

@admin_bp.route('/bulk-enrollment')
@login_required
@staff_required
def bulk_enrollment():
    """Enhanced bulk enrollment management interface with proper initialization."""
    try:
        # Get basic enrollment statistics
        enrollment_stats = EnrollmentService.get_enrollment_statistics()

        # Get overview by processing mode
        constraint_based_result = EnrollmentService.get_bulk_enrollment_candidates_optimized(
            mode=BulkEnrollmentMode.CONSTRAINT_BASED,
            limit=10  # Small limit for overview
        )

        override_mode_result = EnrollmentService.get_bulk_enrollment_candidates_optimized(
            mode=BulkEnrollmentMode.ADMIN_OVERRIDE,
            limit=10  # Small limit for overview
        )

        # Session capacity overview (optional)
        try:
            from app.services.session_classroom_service import SessionClassroomService
            classroom_utilization = SessionClassroomService.get_classroom_utilization_summary()
        except Exception:
            classroom_utilization = {}

        # Default constraints for UI initialization
        default_constraints = {
            'processing_modes': {
                'constraint_based': {
                    'label': 'Standard (Ready Students Only)',
                    'description': 'Process only students with verified email and payment',
                    'candidates': constraint_based_result['total_count']
                },
                'admin_override': {
                    'label': 'Administrative Override',
                    'description': 'Process students regardless of verification status',
                    'candidates': override_mode_result['total_count']
                }
            },
            'payment_status_options': [
                {'value': 'verified', 'label': 'Admin Verified', 'description': 'Payment confirmed by administrator'},
                {'value': 'paid', 'label': 'Awaiting Verification',
                 'description': 'Receipt uploaded, pending admin review'},
                {'value': 'unpaid', 'label': 'No Payment', 'description': 'No payment receipt uploaded'}
            ]
        }

        return render_template(
            'admin/enrollment/bulk_enrollment.html',
            enrollment_stats=enrollment_stats,
            constraint_based_analysis=constraint_based_result['analysis'],
            override_mode_analysis=override_mode_result['analysis'],
            classroom_utilization=classroom_utilization,
            default_constraints=default_constraints,
            processing_modes=BulkEnrollmentMode
        )

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment interface error: {str(e)}")
        flash('Error loading bulk enrollment interface.', 'error')
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/bulk-enrollment/preview', methods=['POST'])
@login_required
@staff_required
def bulk_enrollment_preview():
    """Enhanced AJAX endpoint to preview bulk enrollment candidates with flexible constraints."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    try:
        data = request.get_json()

        # Parse and validate request parameters
        constraints, mode, force_override, limit, offset = parse_bulk_enrollment_request(data)

        current_app.logger.info(f"Bulk enrollment preview: mode={mode}, constraints={constraints}")

        # Get candidates using optimized service method
        result = EnrollmentService.get_bulk_enrollment_candidates_optimized(
            constraints=constraints,
            mode=mode,
            limit=limit,
            offset=offset
        )

        # Format preview data (limit to 50 for performance)
        response_data = {
            'success': True,
            'total_count': result['total_count'],
            'analysis': result['analysis'],
            'capacity_impact': result['capacity_impact'],
            'processing_mode': result['processing_mode'],
            'constraints_applied': result['constraints_applied'],
            'query_performance': result['query_performance'],
            'preview_data': []
        }

        # Add override warnings for admin override mode
        if mode == BulkEnrollmentMode.ADMIN_OVERRIDE:
            response_data['override_warnings'] = result.get('override_warnings', [])

        for enrollment in result['preview_enrollments'][:50]:
            enrollment_data = {
                'id': str(enrollment.id),
                'application_number': enrollment.application_number,
                'full_name': enrollment.full_name,
                'email': enrollment.email,
                'has_laptop': enrollment.has_laptop,
                'email_verified': enrollment.email_verified,
                'payment_status': enrollment.payment_status,
                'submitted_at': enrollment.submitted_at.isoformat() if enrollment.submitted_at else None,
                'is_ready': enrollment.is_ready_for_enrollment()
            }

            # Add constraint violation indicators for override mode
            if mode == BulkEnrollmentMode.ADMIN_OVERRIDE:
                violations = []
                if not enrollment.email_verified:
                    violations.append('email_unverified')
                if enrollment.payment_status != PaymentStatus.VERIFIED:
                    violations.append('payment_unverified')
                enrollment_data['constraint_violations'] = violations
                enrollment_data['requires_override'] = len(violations) > 0

            response_data['preview_data'].append(enrollment_data)

        return jsonify(response_data)

    except ValueError as e:
        current_app.logger.warning(f"Bulk enrollment preview validation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment preview error: {str(e)}")
        return jsonify({'success': False, 'error': 'Preview failed'}), 500


@admin_bp.route('/bulk-enrollment/process', methods=['POST'])
@login_required
@staff_required
def process_bulk_enrollment():
    """Enhanced bulk enrollment processing with flexible modes and constraint handling."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    try:
        data = request.get_json()

        # Validate enrollment IDs
        enrollment_ids = validate_enrollment_ids(data.get('enrollment_ids', []))

        # Parse processing parameters
        constraints, mode, force_override, _, _ = parse_bulk_enrollment_request(data)

        # Additional processing parameters
        send_emails = bool(data.get('send_emails', True))
        batch_size = min(int(data.get('batch_size', 25)), 50)  # Cap batch size

        current_app.logger.info(
            f"Starting bulk enrollment: {len(enrollment_ids)} enrollments, mode={mode}, force_override={force_override}")

        # Process enrollments using flexible service method
        results = EnrollmentService.bulk_process_enrollments_flexible(
            enrollment_ids=enrollment_ids,
            mode=mode,
            constraints=constraints,
            processed_by_user_id=str(current_user.id),
            send_emails=send_emails,
            batch_size=batch_size,
            force_override=force_override
        )

        # Generate success message based on results
        success_message_parts = []
        if results['processed'] > 0:
            success_message_parts.append(f"{results['processed']} participants created")
        if results.get('override_processed', 0) > 0:
            success_message_parts.append(f"{results['override_processed']} override enrollments processed")
        if results['failed'] > 0:
            success_message_parts.append(f"{results['failed']} failed")
        if results['skipped'] > 0:
            success_message_parts.append(f"{results['skipped']} skipped")

        success_message = f"Bulk enrollment completed: {', '.join(success_message_parts)}"

        # Format comprehensive response
        response = {
            'success': True,
            'message': success_message,
            'processing_mode': results['processing_mode'],
            'results': {
                'total_requested': results['total_requested'],
                'processed': results['processed'],
                'override_processed': results.get('override_processed', 0),
                'failed': results['failed'],
                'skipped': results['skipped'],
                'duration': results.get('duration', 0),
                'session_assignments': results['session_assignments'],
                'classroom_distribution': results['classroom_distribution']
            },
            'details': {
                'created_participants': results['created_participants'][:20],  # Limit for response size
                'override_enrollments': results.get('override_enrollments', [])[:10],
                'failed_enrollments': results['failed_enrollments'],
                'skipped_enrollments': results['skipped_enrollments'][:10]  # Limit for response size
            },
            'eligibility_check': results.get('eligibility_check', {}),
            'audit_info': {
                'force_override_used': results.get('force_override_used', False),
                'constraints_applied': results.get('constraints_applied', {}),
                'processed_by': current_user.id,
                'processing_started': results.get('started_at').isoformat() if results.get('started_at') else None,
                'processing_completed': results.get('completed_at').isoformat() if results.get('completed_at') else None
            }
        }

        # Add warnings for override operations
        if mode == BulkEnrollmentMode.ADMIN_OVERRIDE or force_override:
            response['override_warnings'] = {
                'message': 'Administrative override was used to process enrollments that did not meet standard criteria',
                'processed_count': results.get('override_processed', 0),
                'audit_trail_available': True
            }

        return jsonify(response)

    except ValueError as e:
        current_app.logger.warning(f"Bulk enrollment processing validation error: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 400

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment processing error: {str(e)}")
        return jsonify({'success': False, 'message': f'Processing failed: {str(e)}'}), 500


@admin_bp.route('/bulk-enrollment/validate', methods=['POST'])
@login_required
@staff_required
def validate_bulk_enrollment():
    """Pre-validate bulk enrollment request for eligibility and impact assessment."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    try:
        data = request.get_json()

        # Validate enrollment IDs
        enrollment_ids = validate_enrollment_ids(data.get('enrollment_ids', []))

        # Parse processing parameters
        constraints, mode, force_override, _, _ = parse_bulk_enrollment_request(data)

        # Quick eligibility validation using service method
        eligibility_result = EnrollmentService._validate_bulk_enrollment_eligibility(
            enrollment_ids, mode, constraints, force_override
        )

        # Capacity impact analysis for eligible enrollments
        if eligibility_result['eligible_ids']:
            # Get sample of eligible enrollments for impact analysis
            sample_size = min(50, len(eligibility_result['eligible_ids']))
            sample_ids = eligibility_result['eligible_ids'][:sample_size]

            sample_enrollments = (
                db.session.query(StudentEnrollment)
                .filter(StudentEnrollment.id.in_(sample_ids))
                .options(db.load_only(StudentEnrollment.has_laptop))
                .all()
            )

            capacity_impact = EnrollmentService._analyze_bulk_capacity_impact_optimized(sample_enrollments)
        else:
            capacity_impact = {'total_impact': 0, 'laptop_classroom_impact': 0, 'no_laptop_classroom_impact': 0}

        response = {
            'success': True,
            'eligibility': eligibility_result,
            'capacity_impact': capacity_impact,
            'processing_mode': mode,
            'validation_warnings': [],
            'recommendations': []
        }

        # Add warnings and recommendations
        if eligibility_result['override_candidates']:
            response['validation_warnings'].append({
                'type': 'constraint_violations',
                'message': f"{len(eligibility_result['override_candidates'])} enrollments have constraint violations",
                'details': eligibility_result['override_candidates'][:5]  # Sample
            })

        if eligibility_result['validation_summary']['ineligible'] > 0:
            response['validation_warnings'].append({
                'type': 'ineligible_enrollments',
                'message': f"{eligibility_result['validation_summary']['ineligible']} enrollments cannot be processed",
                'count': eligibility_result['validation_summary']['ineligible']
            })

        # Processing recommendations
        if mode == BulkEnrollmentMode.CONSTRAINT_BASED and eligibility_result['override_candidates']:
            response['recommendations'].append({
                'type': 'consider_override_mode',
                'message': 'Consider using Administrative Override mode to process additional candidates',
                'additional_candidates': len(eligibility_result['override_candidates'])
            })

        return jsonify(response)

    except ValueError as e:
        current_app.logger.warning(f"Bulk enrollment validation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        current_app.logger.error(f"Bulk enrollment validation error: {str(e)}")
        return jsonify({'success': False, 'error': 'Validation failed'}), 500


@admin_bp.route('/bulk-enrollment/export-results', methods=['POST'])
@login_required
@staff_required
def export_bulk_enrollment_results():
    """Enhanced CSV export with override tracking and comprehensive audit information."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    try:
        data = request.get_json()
        results_data = data.get('results')

        if not results_data:
            return jsonify({'error': 'No results data provided'}), 400

        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Enhanced CSV headers
        writer.writerow([
            'Application Number', 'Participant ID', 'Full Name', 'Email',
            'Username', 'Password', 'Classroom', 'Saturday Session', 'Sunday Session',
            'Processing Status', 'Processing Mode', 'Override Used', 'Override Reasons',
            'Processed At', 'Processing Duration'
        ])

        # Write successful standard enrollments
        for participant in results_data.get('created_participants', []):
            writer.writerow([
                participant['application_number'],
                participant['participant_id'],
                participant.get('full_name', ''),
                participant.get('email', ''),
                participant['username'],
                participant['password'],
                participant['classroom'],
                participant.get('saturday_session', ''),
                participant.get('sunday_session', ''),
                'Successfully Created',
                results_data.get('processing_mode', 'constraint_based'),
                'No',
                '',
                participant.get('processed_at', ''),
                ''
            ])

        # Write override enrollments
        for participant in results_data.get('override_enrollments', []):
            override_reasons = ', '.join(participant.get('override_reasons', []))
            writer.writerow([
                participant['application_number'],
                participant['participant_id'],
                participant.get('full_name', ''),
                participant.get('email', ''),
                participant['username'],
                participant['password'],
                participant['classroom'],
                participant.get('saturday_session', ''),
                participant.get('sunday_session', ''),
                'Successfully Created (Override)',
                results_data.get('processing_mode', 'admin_override'),
                'Yes',
                override_reasons,
                participant.get('processed_at', ''),
                ''
            ])

        # Write failed enrollments
        for failed in results_data.get('failed_enrollments', []):
            writer.writerow([
                failed['application_number'],
                '', '', '', '', '', '', '', '',
                f"Failed: {failed['error']}",
                results_data.get('processing_mode', ''),
                '', '',
                failed.get('failed_at', ''),
                ''
            ])

        # Write skipped enrollments
        for skipped in results_data.get('skipped_enrollments', []):
            writer.writerow([
                skipped.get('application_number', skipped['enrollment_id']),
                '', '', '', '', '', '', '', '',
                f"Skipped: {skipped['reason']}",
                results_data.get('processing_mode', ''),
                '', '',
                skipped.get('skipped_at', ''),
                ''
            ])

        # Create response with enhanced filename
        output.seek(0)
        processing_mode = results_data.get('processing_mode', 'bulk')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bulk_enrollment_{processing_mode}_{timestamp}.csv"

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'

        return response

    except Exception as e:
        current_app.logger.error(f"Export results error: {str(e)}")
        return jsonify({'error': 'Export failed'}), 500


@admin_bp.route('/bulk-enrollment/progress/<task_id>')
@login_required
@staff_required
def bulk_enrollment_progress(task_id):
    """Get progress of bulk enrollment processing (placeholder for future async implementation)."""
    # This remains a placeholder for now
    # Can be enhanced later for true async processing with Celery/Redis
    return jsonify({
        'task_id': task_id,
        'status': 'completed',
        'progress': 100,
        'message': 'Bulk processing completed',
        'results_available': True
    })


# Additional helper endpoint for mode information
@admin_bp.route('/bulk-enrollment/modes')
@login_required
@staff_required
def get_bulk_enrollment_modes():
    """Get available bulk enrollment processing modes and their descriptions."""
    modes = {
        BulkEnrollmentMode.CONSTRAINT_BASED: {
            'label': 'Standard Processing',
            'description': 'Process only students who meet all enrollment criteria (email verified, payment verified)',
            'requirements': ['Email verified', 'Payment admin-verified', 'Ready status'],
            'safe_for_automation': True
        },
        BulkEnrollmentMode.ADMIN_OVERRIDE: {
            'label': 'Administrative Override',
            'description': 'Process students regardless of verification status (requires admin approval)',
            'requirements': ['Admin oversight required', 'Audit trail maintained'],
            'safe_for_automation': False,
            'warnings': ['May process unverified emails', 'May process unverified payments']
        }
    }

    return jsonify({
        'success': True,
        'modes': modes,
        'default_mode': BulkEnrollmentMode.CONSTRAINT_BASED
    })

def parse_bulk_enrollment_request(data):
    """
    Parse and validate bulk enrollment request parameters.
    Handles boolean string conversion and constraint validation.
    """
    constraints = {}

    # Boolean parameter parsing (frontend sends "true"/"false" strings)
    if 'email_verified' in data and data['email_verified'] not in [None, '']:
        constraints['email_verified'] = str(data['email_verified']).lower() == 'true'

    if 'has_laptop' in data and data['has_laptop'] not in [None, '']:
        constraints['has_laptop'] = str(data['has_laptop']).lower() == 'true'

    # Payment status enum validation
    if 'payment_status' in data and data['payment_status']:
        payment_status = data['payment_status']
        valid_payment_statuses = ['unpaid', 'paid', 'verified']
        if payment_status in valid_payment_statuses:
            constraints['payment_status'] = payment_status
        else:
            raise ValueError(f"Invalid payment_status: {payment_status}. Must be one of: {valid_payment_statuses}")

    # Processing mode parsing
    mode = data.get('processing_mode', BulkEnrollmentMode.CONSTRAINT_BASED)
    valid_modes = [BulkEnrollmentMode.CONSTRAINT_BASED, BulkEnrollmentMode.ADMIN_OVERRIDE]
    if mode not in valid_modes:
        mode = BulkEnrollmentMode.CONSTRAINT_BASED  # Default fallback

    # Override settings
    force_override = bool(data.get('force_override', False))

    # Pagination parameters
    limit = min(int(data.get('limit', 500)), 1000)  # Increased limit, cap at 1000
    offset = max(int(data.get('offset', 0)), 0)

    return constraints, mode, force_override, limit, offset


def validate_enrollment_ids(enrollment_ids: List[str]) -> List[str]:
    """Validate enrollment IDs list (UUIDs) - simplified version."""
    if not enrollment_ids:
        raise ValueError("No enrollment IDs provided")

    if not isinstance(enrollment_ids, list):
        raise ValueError("enrollment_ids must be a list")

    if len(enrollment_ids) > 1000:
        raise ValueError("Too many enrollments selected (maximum 1000 allowed)")

    # Ensure all are strings and not empty
    validated_ids = []
    for enrollment_id in enrollment_ids:
        clean_id = str(enrollment_id).strip()
        if not clean_id:
            raise ValueError("Empty enrollment ID provided")
        validated_ids.append(clean_id)

    return validated_ids
