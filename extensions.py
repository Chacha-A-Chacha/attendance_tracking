# extensions.py
"""
Flask extensions initialization.
This file initializes all Flask extensions to avoid circular imports.
Extensions are initialized here and then bound to the app in the application factory.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from .utils.enhanced_email import EnhancedEmailService

# Initialize extensions without app binding
db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
email_service = EnhancedEmailService()


def init_extensions(app):
    """
    Initialize all extensions with the Flask app.
    This must be called in the application factory.

    Args:
        app: Flask application instance
    """
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    email_service.init_app(app)

    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        # Import here to avoid circular imports
        from models import User
        return User.query.get(user_id)


def validate_email_config(app):
    """
    Validate email configuration on startup.

    Args:
        app: Flask application instance

    Returns:
        list: List of configuration issues found
    """
    issues = []

    # Check for email suppression settings
    if app.config.get('TESTING') and app.config.get('MAIL_SUPPRESS_SEND', True):
        issues.append("TESTING=True will suppress emails unless MAIL_SUPPRESS_SEND=False")

    if app.config.get('MAIL_SUPPRESS_SEND'):
        issues.append("MAIL_SUPPRESS_SEND=True will prevent email sending")

    # Check required configuration
    required = ['MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER']
    missing = [key for key in required if not app.config.get(key)]
    if missing:
        issues.append(f"Missing required email config: {', '.join(missing)}")

    # Check port configuration
    mail_port = app.config.get('MAIL_PORT')
    use_tls = app.config.get('MAIL_USE_TLS', False)
    use_ssl = app.config.get('MAIL_USE_SSL', False)

    # Check SSL/TLS conflicts
    if use_tls and use_ssl:
        issues.append("Cannot use both MAIL_USE_TLS and MAIL_USE_SSL simultaneously")

    # Check port/security alignment
    if mail_port == 465 and use_tls and not use_ssl:
        issues.append("Port 465 typically uses SSL, not TLS. Consider using port 587 for TLS")
    elif mail_port == 587 and use_ssl and not use_tls:
        issues.append("Port 587 typically uses TLS, not SSL. Consider using port 465 for SSL")

    # Gmail specific checks
    if 'gmail.com' in app.config.get('MAIL_SERVER', ''):
        password = app.config.get('MAIL_PASSWORD', '')
        if password and len(password) < 16:
            issues.append("Gmail requires App Password (16 characters) since May 2022")

    return issues
