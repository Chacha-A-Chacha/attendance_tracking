# extensions.py
"""
Flask extensions initialization.
This file initializes all Flask extensions to avoid circular imports.
Extensions are initialized here and then bound to the app in the application factory.
"""

from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager

from app.utils.enhanced_email import EnhancedEmailService
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError, DisconnectionError
import time
import logging
import threading

# Initialize extensions without app binding
db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
email_service = EnhancedEmailService()

# Connection monitoring
connection_stats = {
    'total_connections': 0,
    'failed_connections': 0,
    'last_check': 0,
    'healthy': True
}
connection_lock = threading.Lock()

logger = logging.getLogger(__name__)


def add_connection_retry(engine, retries=3, delay=1):
    """
    Add retry mechanism for database connections.

    Args:
        engine: SQLAlchemy engine instance
        retries (int): Number of retry attempts
        delay (int): Initial delay between retries in seconds
    """

    @event.listens_for(engine, "engine_connect")
    def ping_connection(connection, branch):
        if branch:
            # "branch" refers to a sub-connection of a connection,
            # we don't want to bother pinging on these.
            return

        # Turn off the close-with-result flag
        save_should_close_with_result = connection.should_close_with_result
        connection.should_close_with_result = False

        try:
            # Use a transaction to properly handle the connection test
            with connection.begin():
                # Run a simple SELECT 1 to check the connection
                connection.execute(text("SELECT 1"))

            # Update connection stats
            with connection_lock:
                connection_stats['total_connections'] += 1
                connection_stats['healthy'] = True

        except OperationalError as err:
            # Catch operational errors and attempt retry
            if hasattr(err, 'orig') and hasattr(err.orig, 'args') and err.orig.args[0] in (2006, 2013, 2014, 2045,
                                                                                           2055):
                # MySQL has gone away or connection lost errors
                logger.warning(f"Database connection error: {err}. Attempting to reconnect...")

                # Update stats
                with connection_lock:
                    connection_stats['failed_connections'] += 1

                # Retry logic
                for attempt in range(retries):
                    try:
                        time.sleep(delay * (attempt + 1))  # Exponential backoff
                        with connection.begin():
                            connection.execute(text("SELECT 1"))  # Test connection
                        logger.info("Database reconnected successfully")

                        with connection_lock:
                            connection_stats['healthy'] = True
                        break
                    except OperationalError:
                        if attempt == retries - 1:
                            logger.error("Failed to reconnect to database after multiple attempts")
                            with connection_lock:
                                connection_stats['healthy'] = False
                            raise
            else:
                raise
        except Exception as e:
            # Handle any other exceptions
            logger.warning(f"Connection ping failed: {e}")
        finally:
            # Restore the close-with-result flag
            connection.should_close_with_result = save_should_close_with_result


def get_connection_stats():
    """
    Get current database connection statistics.

    Returns:
        dict: Connection statistics
    """
    with connection_lock:
        return connection_stats.copy()


def check_database_health():
    """
    Check if the database connection is healthy.
    This function requires an active Flask application context.

    Returns:
        tuple: (bool, str) indicating health status and message
    """
    try:
        # Check if we have a current app context
        if not current_app:
            return False, "No application context available"

        # Use a separate connection to avoid transaction issues
        with current_app.app_context():
            # Create a new connection specifically for health checks
            connection = db.engine.connect()
            try:
                # Execute health check query within a transaction
                with connection.begin():
                    result = connection.execute(text("SELECT 1"))
                    result.fetchone()  # Consume the result

                with connection_lock:
                    connection_stats['healthy'] = True
                    connection_stats['last_check'] = time.time()

                return True, "Database connection is healthy"
            finally:
                # Always close the connection
                connection.close()

    except Exception as e:
        logger.error(f"Database health check failed: {e}")

        with connection_lock:
            connection_stats['healthy'] = False
            connection_stats['last_check'] = time.time()

        return False, f"Database connection failed: {str(e)}"


def init_extensions(app):
    """
    Initialize all extensions with proper order and configuration.

    Args:
        app: Flask application instance
    """
    # Step 1: Initialize database first (required by other extensions)
    db.init_app(app)
    migrate.init_app(app, db)

    # Step 2: Initialize Flask-Login (requires SECRET_KEY from config)
    login_manager.init_app(app)

    # Step 3: Configure Flask-Login settings
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'basic'  # More reliable than 'strong'

    # Step 4: Initialize CSRF protection (after login manager)
    csrf.init_app(app)

    # Step 5: Initialize email service
    email_service.init_app(app)

    # Step 6: Set up database connection retry for MySQL (requires db)
    with app.app_context():
        if app.config['SQLALCHEMY_DATABASE_URI'] and app.config['SQLALCHEMY_DATABASE_URI'].startswith('mysql'):
            add_connection_retry(
                db.engine,
                retries=app.config.get('DB_CONNECTION_RETRIES', 3),
                delay=app.config.get('DB_RETRY_DELAY', 2)
            )

            app.logger.info(f"Initialized MySQL connection with retry mechanism. "
                            f"Retries: {app.config.get('DB_CONNECTION_RETRIES', 3)}, "
                            f"Delay: {app.config.get('DB_RETRY_DELAY', 2)}s")

    # Step 7: Define user_loader callback (requires db and User model)
    @login_manager.user_loader
    def load_user(user_id):
        # Import here to avoid circular imports
        from app.models import User

        # Check database health before querying
        healthy, message = check_database_health()
        if not healthy:
            logger.error(f"Database unhealthy during user load: {message}")
            return None

        return User.query.get(user_id)

    app.logger.info("Extensions initialized successfully in correct order")


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


# Database health check thread
def start_database_health_monitor(app, interval=300):
    """
    Start a background thread to monitor database health.

    Args:
        app: Flask application instance
        interval (int): Health check interval in seconds
    """

    def monitor():
        while True:
            try:
                # Use app context for the health check
                with app.app_context():
                    healthy, message = check_database_health()
                    if not healthy:
                        logger.warning(f"Database health monitor: {message}")
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Database health monitor error: {e}")
                time.sleep(interval)

    # Only start in production or if explicitly enabled
    if not app.debug or app.config.get('ENABLE_DB_HEALTH_MONITOR', False):
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        logger.info("Started database health monitor thread")
