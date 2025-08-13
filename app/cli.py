# cli.py
"""
Flask CLI commands for the enrollment system.
This module contains all custom CLI commands separated from the main application.
"""

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db


@click.command("init-reassignments-count")
@with_appcontext
def init_reassignments_count():
    """Initialize reassignments_count for all participants."""
    from models import Participant

    try:
        participants = Participant.query.all()
        for participant in participants:
            # Set initial value (usually 0)
            participant.reassignments_count = 0

        db.session.commit()
        click.echo(f"Updated {len(participants)} participants with initial reassignments count.")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error updating reassignments count: {str(e)}", err=True)
        raise


@click.command("reset-session-assignments")
@click.argument("classroom")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@with_appcontext
def reset_session_assignments(classroom, dry_run):
    """
    Reset session assignments for participants in a specific classroom.

    This allows them to request reassignment to their preferred sessions.

    Example usage:
        flask reset-session-assignments 203         # Reset assignments for classroom 203
        flask reset-session-assignments 205 --dry-run  # Preview changes without applying them
    """
    from models import Participant

    try:
        # Validate classroom input
        valid_classrooms = [
            current_app.config['LAPTOP_CLASSROOM'],
            current_app.config['NO_LAPTOP_CLASSROOM']
        ]

        if classroom not in valid_classrooms:
            click.echo(f"Error: Invalid classroom. Valid options are: {', '.join(valid_classrooms)}", err=True)
            return

        # Query participants in the specified classroom
        participants = Participant.query.filter_by(classroom=classroom).all()

        if not participants:
            click.echo(f"No participants found in classroom {classroom}")
            return

        # Record current sessions for each participant before making changes
        summary = []
        for p in participants:
            saturday_session = p.saturday_session.time_slot if p.saturday_session else "None"
            sunday_session = p.sunday_session.time_slot if p.sunday_session else "None"

            summary.append({
                'id': p.id,
                'unique_id': p.unique_id,
                'name': p.full_name,
                'saturday_session': saturday_session,
                'sunday_session': sunday_session
            })

        # Print summary of what will be changed
        click.echo(f"Found {len(participants)} participants in classroom {classroom}")
        click.echo("\nCurrent Session Assignments:")
        click.echo("-" * 80)
        click.echo(f"{'ID':<6} {'Name':<30} {'Saturday Session':<25} {'Sunday Session':<25}")
        click.echo("-" * 80)

        for p in summary:
            click.echo(
                f"{p['unique_id']:<6} {p['name'][:30]:<30} {p['saturday_session']:<25} {p['sunday_session']:<25}")

        # If this is a dry run, stop here
        if dry_run:
            click.echo("\nDRY RUN - No changes were made. Run without --dry-run to apply changes.")
            return

        # Confirm before proceeding
        if not click.confirm("\nAre you sure you want to reset session assignments for these participants?"):
            click.echo("Operation cancelled.")
            return

        # Get default sessions
        from utils.session_mapper import get_default_session

        # Track changes
        reset_count = 0
        reset_errors = []

        # Process each participant
        for p in participants:
            try:
                # Reset to default sessions
                default_saturday = get_default_session('Saturday')
                default_sunday = get_default_session('Sunday')

                if default_saturday and default_sunday:
                    p.saturday_session_id = default_saturday.id
                    p.sunday_session_id = default_sunday.id
                    p.reassignments_count = 0  # Reset reassignment counter
                    reset_count += 1
                else:
                    reset_errors.append(f"No default sessions available for {p.unique_id} ({p.full_name})")
                    continue

            except Exception as e:
                reset_errors.append(f"Error resetting {p.unique_id} ({p.full_name}): {str(e)}")

        # Commit changes
        if reset_count > 0:
            try:
                db.session.commit()
                click.echo(f"\nSuccessfully reset session assignments for {reset_count} participants.")
            except Exception as e:
                db.session.rollback()
                click.echo(f"\nError committing changes: {str(e)}", err=True)
                return

        # Report any errors
        if reset_errors:
            click.echo("\nThe following errors occurred:")
            for error in reset_errors:
                click.echo(f"- {error}")

        click.echo("\nDone! Participants can now request reassignment to their preferred sessions.")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Command failed: {str(e)}", err=True)
        raise


@click.command("create-admin-user")
@click.option("--username", prompt=True, help="Admin username")
@click.option("--email", prompt=True, help="Admin email address")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password")
@with_appcontext
def create_admin_user(username, email, password):
    """Create an admin user for the system."""
    from models import User, RoleType

    try:
        # Check if user already exists
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            click.echo(f"User with username '{username}' or email '{email}' already exists.", err=True)
            return

        # Create admin user
        admin_user = User(
            username=username,
            email=email,
            first_name="Admin",
            last_name="User",
            is_verified=True,
            is_active=True
        )
        admin_user.set_password(password)

        # Add admin role
        admin_user.add_role(RoleType.ADMIN)

        db.session.add(admin_user)
        db.session.commit()

        click.echo(f"Admin user '{username}' created successfully.")

    except Exception as e:
        db.session.rollback()
        click.echo(f"Error creating admin user: {str(e)}", err=True)
        raise


@click.command("test-email")
@click.option("--recipient", prompt=True, help="Email recipient")
@click.option("--subject", default="Test Email", help="Email subject")
@with_appcontext
def test_email_command(recipient, subject):
    """Send a test email to verify email configuration."""
    from extensions import email_service

    try:
        # Send test email using the email service
        task_id = email_service.send_simple_test_email(
            recipient=recipient,
            subject=subject,
            message="This is a test email from the Flask enrollment system."
        )

        click.echo(f"Test email queued successfully. Task ID: {task_id}")
        click.echo(f"Email sent to: {recipient}")
        click.echo("Check the recipient's inbox and the application logs for delivery status.")

    except Exception as e:
        click.echo(f"Failed to send test email: {str(e)}", err=True)
        raise


@click.command("email-status")
@with_appcontext
def email_status_command():
    """Check the status of the email service."""
    from extensions import email_service, validate_email_config

    try:
        # Check configuration
        config_issues = validate_email_config(current_app)

        # Check worker thread
        worker_alive = (
                email_service.worker_thread and
                email_service.worker_thread.is_alive()
        )

        # Check queue
        queue_size = getattr(email_service, 'task_queue', None)
        queue_info = queue_size.qsize() if queue_size else 'unknown'

        # Display status
        click.echo("Email Service Status:")
        click.echo(f"  Worker Thread: {'Running' if worker_alive else 'Stopped'}")
        click.echo(f"  Queue Size: {queue_info}")

        if config_issues:
            click.echo("  Configuration Issues:")
            for issue in config_issues:
                click.echo(f"    - {issue}")
        else:
            click.echo("  Configuration: OK")

        # Get queue statistics if available
        if hasattr(email_service, 'get_queue_stats'):
            stats = email_service.get_queue_stats()
            click.echo(f"  Email Statistics:")
            click.echo(f"    Total: {stats.get('total', 0)}")
            click.echo(f"    Sent: {stats.get('sent', 0)}")
            click.echo(f"    Failed: {stats.get('failed', 0)}")
            click.echo(f"    Queued: {stats.get('queued', 0)}")

    except Exception as e:
        click.echo(f"Error checking email status: {str(e)}", err=True)
        raise


@click.command("init-db")
@with_appcontext
def init_database():
    """Initialize the database with tables and default data."""
    try:
        # Create all tables
        db.create_all()
        click.echo("Database tables created.")

        # Initialize default roles
        from models import Role
        if Role.query.count() == 0:
            Role.create_default_roles()
            click.echo("Default roles created.")

        # Initialize default sessions
        from models import Session
        if Session.query.count() == 0:
            from services.importer import init_sessions
            init_sessions()
            click.echo("Default sessions created.")

        click.echo("Database initialization completed.")

    except Exception as e:
        click.echo(f"Database initialization failed: {str(e)}", err=True)
        raise


def register_cli_commands(app):
    """
    Register all CLI commands with the Flask application.

    Args:
        app: Flask application instance
    """
    app.cli.add_command(init_reassignments_count)
    app.cli.add_command(reset_session_assignments)
    app.cli.add_command(create_admin_user)
    app.cli.add_command(test_email_command)
    app.cli.add_command(email_status_command)
    app.cli.add_command(init_database)
