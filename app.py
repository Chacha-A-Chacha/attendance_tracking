# app.py
"""
Main application entry point.
This module creates the Flask application instance and handles application startup.
"""

import os
from datetime import datetime

from app import create_app
from app.extensions import email_service


def create_application():
    """
    Create and configure the Flask application.

    Returns:
        Flask: Configured application instance
    """
    # Get configuration from environment
    config_name = os.environ.get('FLASK_ENV', 'development')

    # Create application using factory
    app = create_app(config_name)

    # Additional production-specific setup
    if config_name == 'production':
        setup_production_features(app)

    return app


def setup_production_features(app):
    """
    Setup production-specific features.

    Args:
        app: Flask application instance
    """
    # Ensure email service is properly started in production
    if not email_service.worker_thread or not email_service.worker_thread.is_alive():
        email_service.start_worker()
        app.logger.info("Email service worker restarted for production")

    # Setup additional production logging
    import logging
    from logging.handlers import SysLogHandler

    if app.config.get('SYSLOG_SERVER'):
        syslog_handler = SysLogHandler(address=app.config['SYSLOG_SERVER'])
        syslog_handler.setLevel(logging.ERROR)
        app.logger.addHandler(syslog_handler)

    # Ensure all critical directories exist
    critical_dirs = [
        app.config.get('UPLOAD_FOLDER'),
        app.config.get('QR_CODE_FOLDER'),
        app.config.get('REGISTRATION_RECEIPTS_FOLDER'),
        app.config.get('GRADUATION_RECEIPTS_FOLDER')
    ]

    for directory in critical_dirs:
        if directory:
            os.makedirs(directory, exist_ok=True)

    app.logger.info("Production features configured")


# Create the application instance
app = create_application()


# Add context processor for template globals
@app.context_processor
def inject_global_vars():
    """Inject global variables into all templates."""
    return {
        'app_name': app.config.get('SITE_NAME', 'Programming Course'),
        'contact_email': app.config.get('CONTACT_EMAIL', 'info@jaribu.org'),
        'current_year': datetime.now().year
    }


# Development server configuration
if __name__ == '__main__':
    # Only run directly in development
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'

    app.logger.info(f"Starting development server on port {port}, debug={debug}")

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )
