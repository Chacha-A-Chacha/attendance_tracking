# __init__.py
"""
Application factory for the Flask enrollment system.
This module creates and configures the Flask application using the application factory pattern.
"""

import os
import logging
import json
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, flash, redirect, url_for, request, session
from dotenv import load_dotenv
from flask_login import current_user, logout_user

from app.config import config_by_name
from app.extensions import init_extensions, validate_email_config, db, email_service


def setup_logging(app):
    """
    Configure structured logging for the application.

    Args:
        app: Flask application instance
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Configure log format
    log_format = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s'
    )

    # File handler with rotation
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # Configure root logger
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)

    # Configure specific loggers
    # logging.getLogger('email_service').setLevel(logging.DEBUG)
    logging.getLogger('enrollment_service').setLevel(logging.DEBUG)

    # Suppress excessive SQLAlchemy logging in production
    if not app.debug:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    # Forcefully suppress SQLAlchemy logs
    sa_logger = logging.getLogger('sqlalchemy.engine')
    sa_logger.setLevel(logging.WARNING)
    sa_logger.propagate = False


def register_blueprints(app):
    """
    Register all application blueprints.

    Args:
        app: Flask application instance
    """
    try:
        # Import blueprints here to avoid circular imports
        from .controllers.auth import auth_bp
        from .controllers.admin import admin_bp
        from .controllers.check_in import check_in_bp
        from .controllers.enrollment import enrollment_bp
        from .controllers.participant import participant_portal_bp
        from .controllers.api import api_bp
        from .controllers.email import email_bp

        # Register blueprints with their URL prefixes
        app.register_blueprint(auth_bp, url_prefix='/auth')
        app.register_blueprint(admin_bp, url_prefix='/admin')
        app.register_blueprint(check_in_bp, url_prefix='/check-in')
        app.register_blueprint(enrollment_bp)
        app.register_blueprint(participant_portal_bp, url_prefix='/v2/participant')
        app.register_blueprint(api_bp)
        app.register_blueprint(email_bp, url_prefix='/email')

        app.logger.info("All blueprints registered successfully")

    except ImportError as e:
        app.logger.error(f"Failed to import blueprint: {str(e)}")
        raise
    except Exception as e:
        app.logger.error(f"Failed to register blueprints: {str(e)}")
        raise


def register_error_handlers(app):
    """
    Register global error handlers.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'An unexpected error occurred',
            'message': str(e) if app.debug else 'Internal server error'
        }), 500

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({'error': 'Resource not found'}), 404

    @app.errorhandler(403)
    def handle_403(e):
        return jsonify({'error': 'Access forbidden'}), 403

    @app.errorhandler(500)
    def handle_500(e):
        app.logger.error(f"Internal server error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


def register_shell_context(app):
    """
    Register shell context for flask shell command.

    Args:
        app: Flask application instance
    """

    @app.shell_context_processor
    def make_shell_context():
        from models import (
            User, Role, Permission, Participant, Session,
            Attendance, SessionReassignmentRequest, StudentEnrollment
        )
        return {
            'db': db,
            'User': User,
            'Role': Role,
            'Permission': Permission,
            'Participant': Participant,
            'Session': Session,
            'Attendance': Attendance,
            'SessionReassignmentRequest': SessionReassignmentRequest,
            'StudentEnrollment': StudentEnrollment,
            'email_service': email_service
        }


def initialize_default_data(app):
    """
    Initialize system with default data if needed.

    Args:
        app: Flask application instance
    """
    try:
        with app.app_context():
            # Create all database tables
            db.create_all()

            # Initialize default roles if none exist
            from .models import Role
            if Role.query.count() == 0:
                Role.create_default_roles()
                app.logger.info("Default roles initialized")

            # Import default data if file exists
            data_path = os.path.join(app.root_path, 'data', 'sessions_data.xlsx')
            if os.path.exists(data_path):
                app.logger.info(f"Importing default data from {data_path}")
                from .services.importer import import_spreadsheet
                import_spreadsheet(data_path)
            else:
                app.logger.info("No default data file found")

    except Exception as e:
        app.logger.error(f"Failed to initialize default data: {str(e)}", exc_info=True)
        # Don't raise in production - app should still start
        if app.debug:
            raise


def register_health_checks(app):
    """
    Register health check endpoints.

    Args:
        app: Flask application instance
    """

    @app.route('/health')
    def health_check():
        """Basic health check endpoint."""
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.now().isoformat(),
            'version': app.config.get('VERSION', '1.0.0')
        })

    @app.route('/health/email')
    def email_health_check():
        """Email service health check endpoint."""
        try:
            # Validate email configuration
            config_issues = validate_email_config(app)

            # Check worker thread status
            worker_alive = (
                    email_service.worker_thread and
                    email_service.worker_thread.is_alive()
            )

            # Check queue status
            queue_size = getattr(email_service, 'task_queue', None)
            queue_info = queue_size.qsize() if queue_size else 'unknown'

            status = 'healthy' if not config_issues and worker_alive else 'degraded'

            return jsonify({
                'status': status,
                'config_issues': config_issues,
                'worker_thread': 'running' if worker_alive else 'stopped',
                'queue_size': queue_info,
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            app.logger.error(f"Email health check failed: {str(e)}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 503

    @app.route('/health/database')
    def database_health_check():
        """Database health check endpoint."""
        try:
            # Use the new health check function for more detailed information
            from app.extensions import check_database_health, get_connection_stats

            # Perform the health check
            healthy, message = check_database_health()

            # Get connection statistics
            stats = get_connection_stats()

            # If healthy, get additional info like user count
            if healthy:
                try:
                    from models import User
                    user_count = User.query.count()
                    stats['user_count'] = user_count
                except Exception as query_error:
                    # If we can't query users, log but don't fail the health check
                    app.logger.warning(f"Could not get user count: {query_error}")
                    stats['user_count'] = 'unavailable'

            # Return response based on health status
            if healthy:
                return jsonify({
                    'status': 'healthy',
                    'message': message,
                    'stats': stats,
                    'timestamp': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'status': 'unhealthy',
                    'message': message,
                    'stats': stats,
                    'timestamp': datetime.now().isoformat()
                }), 503

        except Exception as e:
            app.logger.error(f"Database health check failed: {str(e)}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 503


def register_session_management(app):
    """Register session timeout and management handlers."""
    from app.services.auth_service import AuthService

    @app.before_request
    def manage_session_timeout():
        """Handle session timeout and activity tracking."""
        # Skip for static files, login route, and logout route
        if (request.endpoint and
                (request.endpoint.startswith('static') or
                 request.endpoint in ['auth.login', 'auth.logout', 'auth.password_reset_request'])):
            return

        if current_user.is_authenticated:
            now = datetime.now()

            # Get role-based timeout
            if current_user.is_staff():
                timeout_minutes = app.config.get('SESSION_TIMEOUT_STAFF', 240)
            elif current_user.is_student():
                timeout_minutes = app.config.get('SESSION_TIMEOUT_STUDENT', 120)
            else:
                timeout_minutes = app.config.get('SESSION_TIMEOUT_DEFAULT', 60)

            timeout_delta = timedelta(minutes=timeout_minutes)

            # Check for session timeout
            if 'last_activity' in session:
                try:
                    last_activity = datetime.fromisoformat(session['last_activity'])
                    if now - last_activity > timeout_delta:
                        # Session expired
                        logout_user()
                        session.clear()
                        flash('Your session has expired due to inactivity. Please log in again.', 'warning')
                        return redirect(url_for('auth.login'))
                except (ValueError, TypeError):
                    # Invalid timestamp, reset it
                    session['last_activity'] = now.isoformat()

            # Update activity timestamp and ensure permanent session
            session['last_activity'] = now.isoformat()
            session.permanent = True
            session.modified = True

    @app.before_request
    def force_permanent_session():
        """Ensure all authenticated sessions are permanent for timeout to work."""
        if current_user.is_authenticated:
            session.permanent = True


def create_app(config_name=None):
    """
    Application factory function.

    Args:
        config_name (str): Configuration name ('development', 'production', 'testing')

    Returns:
        Flask: Configured Flask application instance
    """
    # Load environment variables
    load_dotenv()

    # Create Flask application
    app = Flask(__name__)

    # Load configuration
    config_name = config_name or os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config_by_name[config_name])

    # Setup logging first
    # setup_logging(app)
    app.logger.info(f"Starting application with config: {config_name}")

    # Initialize extensions
    init_extensions(app)
    app.logger.info("Extensions initialized")

    register_session_management(app)

    with app.app_context():
        from app.extensions import start_database_health_monitor
        start_database_health_monitor(app, interval=app.config.get('DB_HEALTH_CHECK_INTERVAL', 300))

    # Validate email configuration
    email_issues = validate_email_config(app)
    if email_issues:
        app.logger.warning(f"Email configuration issues: {'; '.join(email_issues)}")
    else:
        app.logger.info("Email configuration validated successfully")

    # Register components
    register_blueprints(app)
    register_error_handlers(app)
    register_shell_context(app)
    register_health_checks(app)

    # Register CLI commands
    from .cli import register_cli_commands
    register_cli_commands(app)

    # Initialize default data
    # initialize_default_data(app)

    app.logger.info("Application factory completed successfully")

    return app
