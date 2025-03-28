import os

import click
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
from config import config_by_name
from utils.enhanced_email import EnhancedEmailService
from datetime import datetime
import logging
import json
from logging.handlers import RotatingFileHandler

# Initialize extensions
load_dotenv()
db = SQLAlchemy()
migrate = Migrate()
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
    # validate_config(app)

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
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
    with app.app_context():
        db.create_all()
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

    @app.cli.command("init-reassignments-count")
    def init_reassignments_count():
        """Initialize reassignments_count for all participants."""
        from models import Participant

        participants = Participant.query.all()
        for participant in participants:
            # Logic to determine the initial value (usually 0)
            participant.reassignments_count = 0

        db.session.commit()
        print(f"Updated {len(participants)} participants with initial reassignments count.")

    @app.cli.command("reset-session-assignments")
    @click.argument("classroom")
    @click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
    def reset_session_assignments(classroom, dry_run):
        """
        Reset session assignments for participants in a specific classroom.

        This allows them to request reassignment to their preferred sessions.

        Example usage:
            flask reset-session-assignments 203         # Reset assignments for classroom 203
            flask reset-session-assignments 205 --dry-run  # Preview changes without applying them
        """
        from models import Participant

        # Validate classroom input
        valid_classrooms = [
            app.config['LAPTOP_CLASSROOM'],
            app.config['NO_LAPTOP_CLASSROOM']
        ]

        if classroom not in valid_classrooms:
            print(f"Error: Invalid classroom. Valid options are: {', '.join(valid_classrooms)}")
            return

        # Query participants in the specified classroom
        participants = Participant.query.filter_by(classroom=classroom).all()

        if not participants:
            print(f"No participants found in classroom {classroom}")
            return

        # Record current sessions for each participant before making changes
        summary = []
        for p in participants:
            saturday_session = p.saturday_session.time_slot if p.saturday_session else "None"
            sunday_session = p.sunday_session.time_slot if p.sunday_session else "None"

            summary.append({
                'id': p.id,
                'unique_id': p.unique_id,
                'name': p.name,
                'saturday_session': saturday_session,
                'sunday_session': sunday_session
            })

        # Print summary of what will be changed
        print(f"Found {len(participants)} participants in classroom {classroom}")
        print("\nCurrent Session Assignments:")
        print("-" * 80)
        print(f"{'ID':<6} {'Name':<30} {'Saturday Session':<25} {'Sunday Session':<25}")
        print("-" * 80)

        for p in summary:
            print(f"{p['unique_id']:<6} {p['name'][:30]:<30} {p['saturday_session']:<25} {p['sunday_session']:<25}")

        # If this is a dry run, stop here
        if dry_run:
            print("\nDRY RUN - No changes were made. Run without --dry-run to apply changes.")
            return

        # Confirm before proceeding
        confirm = input("\nAre you sure you want to reset session assignments for these participants? (y/n): ")
        if confirm.lower() != 'y':
            print("Operation cancelled.")
            return

        # Reset session assignments and increment reassignment counter
        from services.session_reassignment_service import SessionReassignmentService
        reassignment_service = SessionReassignmentService()

        # Get default sessions from the session mapper
        from utils.session_mapper import get_default_session

        # Track changes
        reset_count = 0
        reset_errors = []

        # Process each participant
        for p in participants:
            try:
                # Store original sessions for logging
                old_saturday = p.saturday_session_id
                old_sunday = p.sunday_session_id

                # Reset to default sessions
                default_saturday = get_default_session('Saturday')
                default_sunday = get_default_session('Sunday')

                if default_saturday and default_sunday:
                    p.saturday_session_id = default_saturday.id
                    p.sunday_session_id = default_sunday.id
                    p.reassignments_count = 0  # Reset reassignment counter
                    reset_count += 1
                else:
                    reset_errors.append(f"No default sessions available for {p.unique_id} ({p.name})")
                    continue

            except Exception as e:
                reset_errors.append(f"Error resetting {p.unique_id} ({p.name}): {str(e)}")

        # Commit changes
        if reset_count > 0:
            try:
                db.session.commit()
                print(f"\nSuccessfully reset session assignments for {reset_count} participants.")
            except Exception as e:
                db.session.rollback()
                print(f"\nError committing changes: {str(e)}")
                return

        # Report any errors
        if reset_errors:
            print("\nThe following errors occurred:")
            for error in reset_errors:
                print(f"- {error}")

        print("\nDone! Participants can now request reassignment to their preferred sessions.")

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


app = create_app()

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0')
