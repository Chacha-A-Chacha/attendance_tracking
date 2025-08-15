# controllers/admin_auth.py
"""
Admin authentication management routes for user administration.
Handles staff user creation, editing, password management, role assignment, and account management.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func

from app.models.user import User, Role, RoleType
from app.models.participant import Participant
from app.forms.auth_forms import (
    AdminUserCreateForm, AdminUserEditForm, AdminPasswordResetForm,
    AccountLockForm, RoleAssignmentForm
)
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.auth import permission_required, role_required, staff_required
from app.models.user import Permission
from app.extensions import db

# Create blueprint
admin_auth_bp = Blueprint('admin_auth', __name__, url_prefix='/admin/users')


@admin_auth_bp.route('/', methods=['GET'])
@login_required
@permission_required(Permission.VIEW_USERS)
def user_list():
    """Admin user management dashboard."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    role_filter = request.args.get('role', '', type=str)
    status_filter = request.args.get('status', '', type=str)

    # Base query with optimized loading
    query = (
        db.session.query(User)
        .options(
            joinedload(User.roles),
            joinedload(User.participant)
        )
    )

    # Apply search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.first_name.ilike(search_pattern),
                User.last_name.ilike(search_pattern)
            )
        )

    # Apply role filter
    if role_filter:
        query = query.join(User.roles).filter(Role.name == role_filter)

    # Apply status filter
    if status_filter == 'active':
        query = query.filter(User.is_active == True)
    elif status_filter == 'inactive':
        query = query.filter(User.is_active == False)
    elif status_filter == 'locked':
        query = query.filter(User.locked_until.isnot(None))

    # Order by creation date (newest first)
    query = query.order_by(User.created_at.desc())

    # Paginate results
    users = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # Get role choices for filter
    roles = db.session.query(Role).filter_by(is_active=True).all()

    # Get user statistics
    stats = {
        'total_users': db.session.query(func.count(User.id)).scalar(),
        'active_users': db.session.query(func.count(User.id)).filter(User.is_active == True).scalar(),
        'locked_users': db.session.query(func.count(User.id)).filter(User.locked_until.isnot(None)).scalar(),
        'staff_users': db.session.query(func.count(User.id)).filter(User.participant_id.is_(None)).scalar(),
        'student_users': db.session.query(func.count(User.id)).filter(User.participant_id.isnot(None)).scalar()
    }

    return render_template(
        'admin/auth/user_list.html',
        users=users,
        roles=roles,
        stats=stats,
        search=search,
        role_filter=role_filter,
        status_filter=status_filter
    )


@admin_auth_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.CREATE_USERS)
def create_user():
    """Create new staff user."""
    form = AdminUserCreateForm()

    if form.validate_on_submit():
        try:
            # Create user
            user, password = UserService.create_user(
                username=form.username.data.strip(),
                email=form.email.data.strip().lower(),
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                password=form.password.data,
                roles=[form.role.data]
            )

            # Send welcome email
            success, task_id = AuthService.send_welcome_email(user.id, password=None)

            flash(f'User {user.username} created successfully!', 'success')

            if success:
                flash('Welcome email has been sent to the user.', 'info')
            else:
                flash('User created but welcome email failed to send.', 'warning')

            return redirect(url_for('admin_auth.user_detail', user_id=user.id))

        except ValueError as e:
            flash(str(e), 'error')
        except Exception as e:
            flash('An error occurred while creating the user.', 'error')
            current_app.logger.error(f"User creation error: {str(e)}")

    return render_template('admin/auth/create_user.html', form=form)


@admin_auth_bp.route('/<user_id>', methods=['GET'])
@login_required
@permission_required(Permission.VIEW_USERS)
def user_detail(user_id):
    """View user details."""
    user = (
        db.session.query(User)
        .options(
            joinedload(User.roles),
            joinedload(User.participant)
        )
        .filter_by(id=user_id)
        .first_or_404()
    )

    # Get user login history
    login_history = AuthService.get_user_login_history(user_id)

    return render_template(
        'admin/auth/user_detail.html',
        user=user,
        login_history=login_history
    )


@admin_auth_bp.route('/<user_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def edit_user(user_id):
    """Edit user details."""
    user = (
        db.session.query(User)
        .options(joinedload(User.roles))
        .filter_by(id=user_id)
        .first_or_404()
    )

    # Check if current user can manage this user
    if not current_user.can_manage_user(user):
        flash('You do not have permission to edit this user.', 'error')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    form = AdminUserEditForm(obj=user)
    form.user_id.data = user_id

    if form.validate_on_submit():
        try:
            # Update user details
            user.username = form.username.data.strip()
            user.email = form.email.data.strip().lower()
            user.first_name = form.first_name.data.strip()
            user.last_name = form.last_name.data.strip()
            user.is_active = form.is_active.data

            db.session.commit()

            flash(f'User {user.username} updated successfully!', 'success')
            return redirect(url_for('admin_auth.user_detail', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating the user.', 'error')
            current_app.logger.error(f"User update error: {str(e)}")

    return render_template('admin/auth/edit_user.html', form=form, user=user)


@admin_auth_bp.route('/<user_id>/reset-password', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def reset_user_password(user_id):
    """Admin-initiated password reset for any user."""
    user = db.session.query(User).filter_by(id=user_id).first_or_404()

    # Check if current user can manage this user
    if not current_user.can_manage_user(user):
        flash('You do not have permission to reset this user\'s password.', 'error')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    form = AdminPasswordResetForm()
    form.user_id.data = user_id

    if form.validate_on_submit():
        try:
            new_password = form.new_password.data
            notify_user = form.notify_user.data
            reason = form.reason.data

            # Reset password
            user.set_password(new_password)
            user.failed_login_attempts = 0
            user.locked_until = None

            db.session.commit()

            # Send notification email if requested
            if notify_user:
                try:
                    AuthService.send_welcome_email(user.id, password=new_password)
                    flash(f'Password reset for {user.username} and notification email sent.', 'success')
                except Exception as e:
                    flash(f'Password reset for {user.username} but email notification failed.', 'warning')
            else:
                flash(f'Password reset for {user.username} successfully.', 'success')

            return redirect(url_for('admin_auth.user_detail', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash('An error occurred while resetting the password.', 'error')
            current_app.logger.error(f"Password reset error: {str(e)}")

    return render_template('admin/auth/reset_password.html', form=form, user=user)


@admin_auth_bp.route('/<user_id>/lock', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def lock_user_account(user_id):
    """Lock user account."""
    user = db.session.query(User).filter_by(id=user_id).first_or_404()

    # Check if current user can manage this user
    if not current_user.can_manage_user(user):
        flash('You do not have permission to lock this user\'s account.', 'error')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    if user.is_locked():
        flash('Account is already locked.', 'info')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    form = AccountLockForm()
    form.user_id.data = user_id
    form.action.data = 'lock'

    if form.validate_on_submit():
        try:
            reason = form.reason.data
            notify_user = form.notify_user.data

            success, message = AuthService.deactivate_user_account(
                user_id=user_id,
                reason=reason,
                deactivated_by_user_id=current_user.id
            )

            if success:
                flash(message, 'success')
            else:
                flash(message, 'error')

            return redirect(url_for('admin_auth.user_detail', user_id=user_id))

        except Exception as e:
            flash('An error occurred while locking the account.', 'error')
            current_app.logger.error(f"Account lock error: {str(e)}")

    return render_template('admin/auth/lock_account.html', form=form, user=user, action='lock')


@admin_auth_bp.route('/<user_id>/unlock', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def unlock_user_account(user_id):
    """Unlock user account."""
    user = db.session.query(User).filter_by(id=user_id).first_or_404()

    # Check if current user can manage this user
    if not current_user.can_manage_user(user):
        flash('You do not have permission to unlock this user\'s account.', 'error')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    if not user.is_locked() and user.is_active:
        flash('Account is not locked.', 'info')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    form = AccountLockForm()
    form.user_id.data = user_id
    form.action.data = 'unlock'

    if form.validate_on_submit():
        try:
            reason = form.reason.data

            # Unlock account and reactivate if needed
            if not user.is_active:
                success, message = AuthService.reactivate_user_account(
                    user_id=user_id,
                    reactivated_by_user_id=current_user.id
                )
            else:
                success, message = AuthService.unlock_user_account(
                    user_id=user_id,
                    unlocked_by_user_id=current_user.id
                )

            if success:
                flash(message, 'success')
            else:
                flash(message, 'error')

            return redirect(url_for('admin_auth.user_detail', user_id=user_id))

        except Exception as e:
            flash('An error occurred while unlocking the account.', 'error')
            current_app.logger.error(f"Account unlock error: {str(e)}")

    return render_template('admin/auth/lock_account.html', form=form, user=user, action='unlock')


@admin_auth_bp.route('/<user_id>/manage-roles', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.MANAGE_ROLES)
def manage_user_roles(user_id):
    """Manage user roles (add/remove)."""
    user = (
        db.session.query(User)
        .options(joinedload(User.roles))
        .filter_by(id=user_id)
        .first_or_404()
    )

    # Check if current user can manage this user
    if not current_user.can_manage_user(user):
        flash('You do not have permission to manage this user\'s roles.', 'error')
        return redirect(url_for('admin_auth.user_detail', user_id=user_id))

    form = RoleAssignmentForm()
    form.user_id.data = user_id

    # Filter role choices based on current user's permissions
    current_user_level = current_user.get_highest_role().hierarchy_level
    available_roles = db.session.query(Role).filter(
        and_(
            Role.is_active == True,
            Role.hierarchy_level < current_user_level
        )
    ).all()

    form.role.choices = [(role.name, role.display_name) for role in available_roles]

    if form.validate_on_submit():
        try:
            role_name = form.role.data
            action = form.action.data
            reason = form.reason.data

            if action == 'add':
                if user.has_role(role_name):
                    flash(f'User already has the {role_name} role.', 'info')
                else:
                    user.add_role(role_name)
                    db.session.commit()
                    flash(f'Role {role_name} added to user {user.username}.', 'success')

            elif action == 'remove':
                if not user.has_role(role_name):
                    flash(f'User does not have the {role_name} role.', 'info')
                else:
                    user.remove_role(role_name)
                    db.session.commit()
                    flash(f'Role {role_name} removed from user {user.username}.', 'success')

            return redirect(url_for('admin_auth.user_detail', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash('An error occurred while managing roles.', 'error')
            current_app.logger.error(f"Role management error: {str(e)}")

    return render_template('admin/auth/manage_roles.html', form=form, user=user)


@admin_auth_bp.route('/create-student-accounts', methods=['GET', 'POST'])
@login_required
@permission_required(Permission.CREATE_USERS)
def create_student_accounts():
    """Bulk create user accounts for participants without accounts."""
    if request.method == 'POST':
        try:
            created_accounts = UserService.bulk_create_student_accounts()

            if created_accounts:
                flash(f'Created {len(created_accounts)} student accounts successfully!', 'success')

                # Send welcome emails
                email_count = 0
                for account in created_accounts:
                    try:
                        AuthService.send_welcome_email(
                            account['user'].id,
                            password=account['password']
                        )
                        email_count += 1
                    except Exception as e:
                        current_app.logger.warning(f"Welcome email failed for {account['username']}: {e}")

                if email_count > 0:
                    flash(f'Welcome emails sent to {email_count} new users.', 'info')
                else:
                    flash('Accounts created but welcome emails failed to send.', 'warning')
            else:
                flash('No new student accounts were created. All participants already have accounts.', 'info')

            return redirect(url_for('admin_auth.user_list'))

        except Exception as e:
            flash('An error occurred while creating student accounts.', 'error')
            current_app.logger.error(f"Bulk student account creation error: {str(e)}")

    # Get participants without user accounts
    participants_without_users = (
        db.session.query(Participant)
        .filter(~db.session.query(User.participant_id)
                .filter(User.participant_id == Participant.id)
                .exists())
        .count()
    )

    return render_template(
        'admin/auth/create_student_accounts.html',
        participants_count=participants_without_users
    )


# AJAX Routes for Admin UX
@admin_auth_bp.route('/search', methods=['POST'])
@login_required
@permission_required(Permission.VIEW_USERS)
def search_users():
    """AJAX endpoint for user search."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    search_term = data.get('search', '').strip()
    limit = data.get('limit', 10)

    if not search_term:
        return jsonify({'users': []})

    search_pattern = f"%{search_term}%"
    users = (
        db.session.query(User)
        .options(joinedload(User.roles))
        .filter(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.first_name.ilike(search_pattern),
                User.last_name.ilike(search_pattern)
            )
        )
        .limit(limit)
        .all()
    )

    user_data = []
    for user in users:
        user_data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.full_name,
            'primary_role': user.primary_role,
            'is_active': user.is_active,
            'is_locked': user.is_locked(),
            'is_student': user.is_student()
        })

    return jsonify({'users': user_data})


@admin_auth_bp.route('/<user_id>/quick-toggle-status', methods=['POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def quick_toggle_user_status(user_id):
    """AJAX endpoint to quickly toggle user active status."""
    user = db.session.query(User).filter_by(id=user_id).first_or_404()

    # Check permissions
    if not current_user.can_manage_user(user):
        return jsonify({'error': 'Permission denied'}), 403

    try:
        if user.is_active:
            success, message = AuthService.deactivate_user_account(
                user_id=user_id,
                reason="Quick toggle by admin",
                deactivated_by_user_id=current_user.id
            )
        else:
            success, message = AuthService.reactivate_user_account(
                user_id=user_id,
                reactivated_by_user_id=current_user.id
            )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'new_status': user.is_active
            })
        else:
            return jsonify({'success': False, 'message': message}), 400

    except Exception as e:
        current_app.logger.error(f"Quick toggle status error: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_auth_bp.route('/<user_id>/quick-unlock', methods=['POST'])
@login_required
@permission_required(Permission.EDIT_USERS)
def quick_unlock_user(user_id):
    """AJAX endpoint to quickly unlock a user account."""
    user = db.session.query(User).filter_by(id=user_id).first_or_404()

    # Check permissions
    if not current_user.can_manage_user(user):
        return jsonify({'error': 'Permission denied'}), 403

    try:
        success, message = AuthService.unlock_user_account(
            user_id=user_id,
            unlocked_by_user_id=current_user.id
        )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'is_locked': user.is_locked()
            })
        else:
            return jsonify({'success': False, 'message': message}), 400

    except Exception as e:
        current_app.logger.error(f"Quick unlock error: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500
