import os
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from config import config_by_name
from utils.enhanced_email import EnhancedEmailService
from datetime import datetime
import logging
import json
from logging.handlers import RotatingFileHandler

# Initialize extensions
db = SQLAlchemy()
email_service = EnhancedEmailService()

def setup_logging(app):
    """Configure structured logging for the application."""
    log_format = json.dumps({
        'timestamp': '%(asctime)s',
        'level': '%(levelname)s',
        'message': '%(message)s',
        'module': '%(module)s',
        'function': '%(funcName)s',
        'pathname': '%(pathname)s',
        'lineno': '%(lineno)d'
    })

    file_handler = RotatingFileHandler('app.log', maxBytes=1024 * 1024 * 10, backupCount=5)
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])
    app.logger = logging.getLogger(__name__)

def validate_config(app):
    """Validate critical configuration settings."""
    required_settings = [
        'SECRET_KEY',
        'MAIL_SERVER',
        'MAIL_PORT',
        'MAIL_USERNAME',
        'MAIL_PASSWORD'
    ]

    for setting in required_settings:
        if not app.config.get(setting):
            raise ValueError(f"Missing required configuration: {setting}")

def create_app(config_name=None):
    """Application factory function."""
    app = Flask(__name__)
    setup_logging(app)

    # Load configuration
    config_name = config_name or os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config_by_name[config_name])
    validate_config(app)

    # Initialize extensions with app
    db.init_app(app)
    email_service.init_app(app)

    # Register blueprints
    from controllers.admin import admin_bp
    from controllers.check_in import check_in_bp
    from controllers.participant import participant_bp
    from controllers.api import api_bp
    from controllers.email import email_bp

    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(check_in_bp, url_prefix='/check-in')
    app.register_blueprint(participant_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(email_bp, url_prefix='/email')

    # Create database tables
    initialize_default_data(app)

    # Add health check endpoint
    @app.route('/health')
    def health_check():
        return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

    # Add error handler
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred', 'message': str(e)}), 500

    return app

def initialize_default_data(app):
    """Initialize system with default data if needed."""
    from models import Session

    try:
        with app.app_context():
            db.create_all()

            if Session.query.count() == 0:
                from services.importer import init_sessions
                init_sessions()

                data_path = os.path.join(app.root_path, 'data', 'sessions_data.xlsx')
                if os.path.exists(data_path):
                    app.logger.info(f"Importing default data from {data_path}")
                    from services.importer import import_spreadsheet
                    import_spreadsheet(data_path)
                else:
                    app.logger.info("No default data file found at data/participants.csv")
    except Exception as e:
        app.logger.error(f"Failed to initialize default data: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0')