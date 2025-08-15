# controllers/auth.py
"""
Authentication routes for user login, logout, password management.
Handles general authentication functionality for all users.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import login_required, logout_user, current_user
from urllib.parse import urlparse, urljoin

from .forms.auth_forms import (
    LoginForm, PasswordResetRequestForm, PasswordResetForm, PasswordChangeForm
)
from app.services.auth_service import AuthService
from app.utils.auth import student_or_staff_required

from . import auth_bp

def is_safe_url(target):
    """Check if redirect target is safe (same domain)."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    # Redirect if already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()

    if request.method == 'GET':
        next_url = request.args.get('next')
        form.next_url.data = next_url

    if form.validate_on_submit():
        identifier = form.identifier.data.strip()
        password = form.password.data
        remember_me = form.remember_me.data

        # Authenticate user
        success, user, message = AuthService.authenticate_user(
            identifier=identifier,
            password=password,
            remember_me=remember_me
        )

        if success:
            flash('Login successful!', 'success')

            # Handle redirect after login
            next_page = form.next_page.data
            if next_page and is_safe_url(next_page):
                return redirect(next_page)

            # Default redirect based on user role
            if user.is_staff():
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('participant.dashboard'))
        else:
            flash(message, 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    """User logout route."""
    username = current_user.username if current_user.is_authenticated else 'Unknown'

    # Logout user
    success = AuthService.logout_user_session()

    if success:
        flash(f'You have been logged out successfully.', 'info')
    else:
        flash('Logout failed. Please try again.', 'error')

    return redirect(url_for('auth.login'))


@auth_bp.route('/password-reset-request', methods=['GET', 'POST'])
def password_reset_request():
    """Request password reset route."""
    # Redirect if already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = PasswordResetRequestForm()

    if form.validate_on_submit():
        email_or_username = form.email_or_username.data.strip()

        # Initiate password reset
        success, message, task_id = AuthService.initiate_password_reset(email_or_username)

        if success:
            flash(message, 'info')
            return redirect(url_for('auth.password_reset_sent'))
        else:
            flash(message, 'error')

    return render_template('auth/password_reset_request.html', form=form)


@auth_bp.route('/password-reset-sent')
def password_reset_sent():
    """Password reset email sent confirmation page."""
    return render_template('auth/password_reset_sent.html')


@auth_bp.route('/reset-password/<user_id>/<token>', methods=['GET', 'POST'])
def reset_password(user_id, token):
    """Complete password reset with token."""
    # Redirect if already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Verify token first
    valid, user, message = AuthService.verify_reset_token(user_id, token)

    if not valid:
        flash(message, 'error')
        return redirect(url_for('auth.password_reset_request'))

    form = PasswordResetForm()
    form.user_id.data = user_id
    form.token.data = token

    if form.validate_on_submit():
        new_password = form.password.data

        # Complete password reset
        success, message, task_id = AuthService.complete_password_reset(
            user_id=user_id,
            token=token,
            new_password=new_password
        )

        if success:
            flash(message, 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(message, 'error')

    return render_template('auth/password_reset.html', form=form, user=user)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password route for authenticated users."""
    form = PasswordChangeForm()

    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data

        # Change password
        success, message = AuthService.change_password(
            user=current_user,
            current_password=current_password,
            new_password=new_password
        )

        if success:
            flash(message, 'success')
            return redirect(url_for('auth.change_password'))
        else:
            flash(message, 'error')

    return render_template('auth/change_password.html', form=form)


@auth_bp.route('/profile', methods=['GET'])
@login_required
def profile():
    """User profile page."""
    return render_template('auth/profile.html', user=current_user)


# AJAX Routes for enhanced UX
@auth_bp.route('/check-login-status', methods=['GET'])
def check_login_status():
    """AJAX endpoint to check current login status."""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'username': current_user.username,
            'full_name': current_user.full_name,
            'role': current_user.primary_role,
            'is_staff': current_user.is_staff(),
            'is_student': current_user.is_student()
        })
    else:
        return jsonify({'authenticated': False})


@auth_bp.route('/validate-password', methods=['POST'])
@login_required
def validate_password():
    """AJAX endpoint to validate current password."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    password = data.get('password', '')

    if not password:
        return jsonify({'valid': False, 'message': 'Password is required'})

    is_valid = current_user.check_password(password)

    return jsonify({
        'valid': is_valid,
        'message': 'Password is correct' if is_valid else 'Password is incorrect'
    })


@auth_bp.route('/check-password-strength', methods=['POST'])
def check_password_strength():
    """AJAX endpoint to check password strength."""
    if not request.is_json:
        return jsonify({'error': 'Invalid request format'}), 400

    data = request.get_json()
    password = data.get('password', '')

    if not password:
        return jsonify({
            'valid': False,
            'message': 'Password is required',
            'score': 0
        })

    valid, message, score = AuthService.validate_password_strength(password)

    # Determine strength level
    if score >= 4:
        strength = 'strong'
        color = 'green'
    elif score >= 3:
        strength = 'moderate'
        color = 'yellow'
    elif score >= 2:
        strength = 'weak'
        color = 'orange'
    else:
        strength = 'very weak'
        color = 'red'

    return jsonify({
        'valid': valid,
        'message': message,
        'score': score,
        'strength': strength,
        'color': color
    })


@auth_bp.route('/session-check', methods=['GET'])
def session_check():
    """AJAX endpoint for session validity check."""
    if current_user.is_authenticated:
        # Check if account is still active and not locked
        if not current_user.is_active:
            logout_user()
            return jsonify({
                'valid': False,
                'reason': 'account_deactivated',
                'message': 'Your account has been deactivated'
            })

        if current_user.is_locked():
            logout_user()
            return jsonify({
                'valid': False,
                'reason': 'account_locked',
                'message': 'Your account has been locked'
            })

        return jsonify({
            'valid': True,
            'username': current_user.username,
            'session_timeout': session.permanent
        })
    else:
        return jsonify({
            'valid': False,
            'reason': 'not_authenticated',
            'message': 'Not authenticated'
        })


@auth_bp.route('/extend-session', methods=['POST'])
@login_required
def extend_session():
    """AJAX endpoint to extend user session."""
    if current_user.is_authenticated and current_user.is_active:
        session.permanent = True
        return jsonify({
            'success': True,
            'message': 'Session extended successfully'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Cannot extend session'
        }), 400


# Error handlers specific to auth blueprint
@auth_bp.errorhandler(404)
def auth_not_found(error):
    """Handle 404 errors in auth blueprint."""
    return render_template('auth/404.html'), 404


@auth_bp.errorhandler(500)
def auth_server_error(error):
    """Handle 500 errors in auth blueprint."""
    return render_template('auth/500.html'), 500


# Context processors for auth templates
@auth_bp.context_processor
def auth_context():
    """Inject common context variables for auth templates."""
    return {
        'site_name': current_app.config.get('SITE_NAME', 'Programming Course'),
        'support_email': current_app.config.get('CONTACT_EMAIL', 'support@example.com'),
        'password_min_length': 8,
        'login_attempts_limit': 5,
        'lockout_duration_minutes': 30
    }
