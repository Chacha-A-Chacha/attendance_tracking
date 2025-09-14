# cli.py
"""
Flask CLI commands for the enrollment system - OPTIMIZED VERSION.
This module contains all custom CLI commands using optimized services.
"""

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db


@click.command("init-reassignments-count")
@with_appcontext
def init_reassignments_count():
    """Initialize reassignments_count for all participants."""
    from app.models import Participant

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
    from app.models import Participant

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
        from app.utils.session_mapper import get_default_session

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
@click.option("--first-name", prompt=True, help="Admin first name")
@click.option("--last-name", prompt=True, help="Admin last name")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password")
@click.option("--no-welcome-email", is_flag=True, help="Skip sending welcome email")
@with_appcontext
def create_admin_user(username, email, first_name, last_name, password, no_welcome_email):
    """Create an admin user for the system using optimized UserService."""
    from app.services.user_service import UserService
    from app.models.user import RoleType

    try:
        # Create admin user using the optimized service
        user, generated_password, task_id = UserService.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,  # Use provided password
            roles=[RoleType.ADMIN],
            send_welcome_email=not no_welcome_email,
            created_by_user_id=None  # System creation
        )

        click.echo(f"✅ Admin user '{username}' created successfully!")
        click.echo(f"   Name: {user.full_name}")
        click.echo(f"   Email: {user.email}")
        click.echo(f"   Role: {user.primary_role}")

        if not no_welcome_email and task_id:
            click.echo(f"   Welcome email queued (Task ID: {task_id})")
        elif not no_welcome_email:
            click.echo("   Welcome email sending failed - check logs")

    except ValueError as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
    except Exception as e:
        click.echo(f"❌ Error creating admin user: {str(e)}", err=True)
        raise


@click.command("create-staff-user")
@click.option("--username", prompt=True, help="Staff username")
@click.option("--email", prompt=True, help="Staff email address")
@click.option("--first-name", prompt=True, help="Staff first name")
@click.option("--last-name", prompt=True, help="Staff last name")
@click.option("--role", prompt=True, type=click.Choice(['teacher', 'chaplain', 'admin']), help="Staff role")
@click.option("--password", help="Staff password (generated if not provided)")
@click.option("--no-welcome-email", is_flag=True, help="Skip sending welcome email")
@with_appcontext
def create_staff_user(username, email, first_name, last_name, role, password, no_welcome_email):
    """Create a staff user (teacher, chaplain, or admin) using optimized UserService."""
    from app.services.user_service import UserService
    from app.models.user import RoleType

    try:
        # Map role strings to RoleType constants
        role_mapping = {
            'teacher': RoleType.TEACHER,
            'chaplain': RoleType.CHAPLAIN,
            'admin': RoleType.ADMIN
        }

        role_type = role_mapping[role]

        # Create staff user using the optimized service
        user, actual_password, task_id = UserService.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,  # Will be generated if None
            roles=[role_type],
            send_welcome_email=not no_welcome_email,
            created_by_user_id=None  # System creation
        )

        click.echo(f"✅ Staff user '{username}' created successfully!")
        click.echo(f"   Name: {user.full_name}")
        click.echo(f"   Email: {user.email}")
        click.echo(f"   Role: {user.primary_role}")

        if not password:  # Password was generated
            click.echo(f"   Generated Password: {actual_password}")
            click.echo("   ⚠️  Please save this password - it won't be shown again!")

        if not no_welcome_email and task_id:
            click.echo(f"   Welcome email queued (Task ID: {task_id})")
        elif not no_welcome_email:
            click.echo("   Welcome email sending failed - check logs")

    except ValueError as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
    except Exception as e:
        click.echo(f"❌ Error creating staff user: {str(e)}", err=True)
        raise


@click.command("create-student-accounts")
@click.option("--no-welcome-emails", is_flag=True, help="Skip sending welcome emails")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@with_appcontext
def create_student_accounts(no_welcome_emails, dry_run):
    """Create user accounts for all participants using optimized bulk creation."""
    from app.services.user_service import UserService

    try:
        if dry_run:
            # Get participants without accounts for preview
            participants = UserService.get_users_without_participant_accounts()

            if not participants:
                click.echo("✅ All participants already have user accounts!")
                return

            click.echo(f"📋 Found {len(participants)} participants without user accounts:")
            click.echo("-" * 80)
            click.echo(f"{'ID':<6} {'Name':<30} {'Email':<35} {'Classroom':<10}")
            click.echo("-" * 80)

            for participant in participants[:20]:  # Show first 20
                click.echo(
                    f"{participant.unique_id:<6} {participant.full_name[:30]:<30} {participant.email[:35]:<35} {participant.classroom:<10}")

            if len(participants) > 20:
                click.echo(f"... and {len(participants) - 20} more")

            click.echo(f"\n📊 Total accounts that would be created: {len(participants)}")
            click.echo("🔁 Run without --dry-run to create these accounts")
            return

        # Perform bulk creation
        click.echo("🔄 Creating user accounts for participants...")

        results = UserService.bulk_create_student_accounts(
            send_welcome_emails=not no_welcome_emails,
            created_by_user_id=None  # System creation
        )

        # Display results
        if results['created_count'] > 0:
            click.echo(f"✅ Successfully created {results['created_count']} student accounts!")

            # Show some created accounts
            if results['created_accounts']:
                click.echo("\n📋 Created accounts:")
                click.echo("-" * 80)
                click.echo(f"{'ID':<6} {'Username':<12} {'Name':<25} {'Password':<12} {'Classroom':<10}")
                click.echo("-" * 80)

                for account in results['created_accounts'][:10]:  # Show first 10
                    participant = account['participant']
                    click.echo(
                        f"{participant.unique_id:<6} {account['username']:<12} {participant.full_name[:25]:<25} {account['password']:<12} {participant.classroom:<10}")

                if len(results['created_accounts']) > 10:
                    click.echo(f"... and {len(results['created_accounts']) - 10} more")

                click.echo("\n⚠️  Please save these passwords - they won't be shown again!")

            # Email status
            if not no_welcome_emails:
                email_count = len(results.get('email_task_ids', []))
                if email_count > 0:
                    click.echo(f"📧 Welcome emails queued: {email_count}")
                else:
                    click.echo("⚠️  No welcome emails were queued - check email service")

        else:
            click.echo("ℹ️  No new accounts were created - all participants already have accounts")

        # Show any failures
        if results['failed_count'] > 0:
            click.echo(f"\n❌ Failed to create {results['failed_count']} accounts:")
            for failed in results['failed_accounts']:
                participant = failed['participant']
                click.echo(f"   {participant.unique_id} ({participant.full_name}): {failed['error']}")

    except Exception as e:
        click.echo(f"❌ Error creating student accounts: {str(e)}", err=True)
        raise


@click.command("promote-student-rep")
@click.argument("user_identifier")  # Can be username, email, or participant ID
@with_appcontext
def promote_student_representative(user_identifier):
    """Promote a student to student representative."""
    from app.services.user_service import UserService
    from app.models import User, Participant

    try:
        # Find user by username, email, or participant unique_id
        user = None

        # Try username first
        user = User.query.filter_by(username=user_identifier).first()

        # Try email
        if not user:
            user = User.query.filter_by(email=user_identifier).first()

        # Try participant unique_id
        if not user:
            participant = Participant.query.filter_by(unique_id=user_identifier).first()
            if participant:
                user = participant.user

        if not user:
            click.echo(f"❌ User not found: {user_identifier}", err=True)
            return

        # Promote using the service
        updated_user = UserService.manage_student_representative_role(
            user_id=user.id,
            action='promote',
            managed_by_user_id=None  # System action
        )

        click.echo(f"✅ Successfully promoted {updated_user.full_name} to Student Representative!")
        click.echo(f"   Username: {updated_user.username}")
        click.echo(f"   Email: {updated_user.email}")
        if updated_user.participant:
            click.echo(f"   Participant ID: {updated_user.participant.unique_id}")
            click.echo(f"   Classroom: {updated_user.participant.classroom}")

    except ValueError as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
    except Exception as e:
        click.echo(f"❌ Error promoting student representative: {str(e)}", err=True)
        raise


@click.command("revoke-student-rep")
@click.argument("user_identifier")  # Can be username, email, or participant ID
@with_appcontext
def revoke_student_representative(user_identifier):
    """Revoke student representative role."""
    from app.services.user_service import UserService
    from app.models import User, Participant

    try:
        # Find user (same logic as promote command)
        user = None

        user = User.query.filter_by(username=user_identifier).first()

        if not user:
            user = User.query.filter_by(email=user_identifier).first()

        if not user:
            participant = Participant.query.filter_by(unique_id=user_identifier).first()
            if participant:
                user = participant.user

        if not user:
            click.echo(f"❌ User not found: {user_identifier}", err=True)
            return

        # Revoke using the service
        updated_user = UserService.manage_student_representative_role(
            user_id=user.id,
            action='revoke',
            managed_by_user_id=None  # System action
        )

        click.echo(f"✅ Successfully revoked Student Representative role from {updated_user.full_name}")
        click.echo(f"   Username: {updated_user.username}")
        click.echo(f"   Current roles: {', '.join([role.display_name for role in updated_user.roles])}")

    except ValueError as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
    except Exception as e:
        click.echo(f"❌ Error revoking student representative: {str(e)}", err=True)
        raise


@click.command("test-email")
@click.option("--recipient", prompt=True, help="Email recipient")
@click.option("--subject", default="Test Email", help="Email subject")
@with_appcontext
def test_email_command(recipient, subject):
    """Send a test email to verify email configuration."""
    from app.extensions import email_service

    try:
        # Send test email using the email service
        task_id = email_service.send_simple_test_email(
            recipient=recipient,
            subject=subject,
            message="This is a test email from the Flask enrollment system."
        )

        click.echo(f"✅ Test email queued successfully!")
        click.echo(f"   Task ID: {task_id}")
        click.echo(f"   Recipient: {recipient}")
        click.echo("📧 Check the recipient's inbox and application logs for delivery status.")

    except Exception as e:
        click.echo(f"❌ Failed to send test email: {str(e)}", err=True)
        raise


@click.command("email-status")
@with_appcontext
def email_status_command():
    """Check the status of the email service."""
    from app.extensions import email_service, validate_email_config

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
        click.echo("📧 Email Service Status:")
        click.echo(f"   Worker Thread: {'🟢 Running' if worker_alive else '🔴 Stopped'}")
        click.echo(f"   Queue Size: {queue_info}")

        if config_issues:
            click.echo("   Configuration Issues:")
            for issue in config_issues:
                click.echo(f"     ⚠️  {issue}")
        else:
            click.echo("   Configuration: ✅ OK")

        # Get queue statistics if available
        if hasattr(email_service, 'get_queue_stats'):
            stats = email_service.get_queue_stats()
            click.echo(f"   Email Statistics:")
            click.echo(f"     Total: {stats.get('total', 0)}")
            click.echo(f"     Sent: {stats.get('sent', 0)}")
            click.echo(f"     Failed: {stats.get('failed', 0)}")
            click.echo(f"     Queued: {stats.get('queued', 0)}")

    except Exception as e:
        click.echo(f"❌ Error checking email status: {str(e)}", err=True)
        raise


@click.command("init-db")
@with_appcontext
def init_database():
    """Initialize the database with tables and default data."""
    try:
        # Create all tables
        db.create_all()
        click.echo("✅ Database tables created.")

        # Initialize default roles
        from app.models import Role
        if Role.query.count() == 0:
            Role.create_default_roles()
            click.echo("✅ Default roles created.")

        # Initialize default sessions
        from app.models import Session
        if Session.query.count() == 0:
            # Import the new service method instead of the old importer
            from app.services.session_classroom_service import SessionClassroomService
            result = SessionClassroomService.init_sessions_from_config()
            if result['success']:
                click.echo(f"Default sessions created: {result['message']}")
            else:
                click.echo(f"Session creation failed: {result.get('error', 'Unknown error')}", err=True)

        click.echo("Database initialization completed.")

    except Exception as e:
        click.echo(f"❌ Database initialization failed: {str(e)}", err=True)
        raise


@click.command("user-stats")
@with_appcontext
def user_statistics():
    """Display comprehensive user statistics."""
    from app.services.user_service import UserService

    try:
        stats = UserService.get_user_statistics()

        click.echo("👥 User Statistics:")
        click.echo(f"   Total Users: {stats['total_users']}")
        click.echo(f"   Active Users: {stats['active_users']}")
        click.echo(f"   Inactive Users: {stats['inactive_users']}")
        click.echo(f"   Staff Users: {stats['staff_users']}")

        click.echo(f"\n📚 Students:")
        click.echo(f"   Total Students: {stats['students']['total']}")
        click.echo(f"   Laptop Classroom: {stats['students']['laptop_classroom']}")
        click.echo(f"   No-Laptop Classroom: {stats['students']['no_laptop_classroom']}")

        click.echo(f"\n🎭 Users by Role:")
        for role_name, role_data in stats['by_role'].items():
            click.echo(f"   {role_data['display_name']}: {role_data['count']}")

        click.echo(f"\n📈 Recent Activity:")
        click.echo(f"   New Registrations (30 days): {stats['recent_registrations']}")

    except Exception as e:
        click.echo(f"❌ Error getting user statistics: {str(e)}", err=True)
        raise


@click.command("users-needing-attention")
@with_appcontext
def users_needing_attention():
    """Display users that may need administrative attention."""
    from app.services.user_service import UserService

    try:
        attention_data = UserService.get_users_needing_attention()

        if attention_data['locked_users']:
            click.echo("🔒 Locked Users:")
            for user in attention_data['locked_users']:
                click.echo(f"   {user.username} ({user.full_name}) - locked until {user.locked_until}")

        if attention_data['high_failed_attempts']:
            click.echo("\n⚠️  High Failed Login Attempts:")
            for user in attention_data['high_failed_attempts']:
                click.echo(f"   {user.username} ({user.full_name}) - {user.failed_login_attempts} attempts")

        if attention_data['never_logged_in']:
            click.echo("\n👤 Never Logged In (>30 days old):")
            for user in attention_data['never_logged_in']:
                days_old = (user.created_at - user.created_at).days if user.created_at else 0
                click.echo(f"   {user.username} ({user.full_name}) - created {days_old} days ago")

        if attention_data['inactive_users']:
            click.echo("\n😴 Inactive Users (>30 days since login):")
            for user in attention_data['inactive_users'][:10]:  # Show top 10
                days_inactive = (user.last_login - user.last_login).days if user.last_login else 0
                click.echo(f"   {user.username} ({user.full_name}) - {days_inactive} days")

    except Exception as e:
        click.echo(f"❌ Error getting users needing attention: {str(e)}", err=True)
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
    app.cli.add_command(create_staff_user)
    app.cli.add_command(create_student_accounts)
    app.cli.add_command(promote_student_representative)
    app.cli.add_command(revoke_student_representative)
    app.cli.add_command(test_email_command)
    app.cli.add_command(email_status_command)
    app.cli.add_command(init_database)
    app.cli.add_command(user_statistics)
    app.cli.add_command(users_needing_attention)


# # Initialize system
# flask init-db
#
# # Create admin user
# flask create-admin-user --username admin --email admin@company.com --first-name John --last-name Admin --password SecurePass123
#
# # Create teaching staff
# flask create-staff-user --username teacher1 --email teacher@company.com --first-name Jane --last-name Teacher --role teacher
#
# # Create student accounts (after enrollment approval)
# flask create-student-accounts
#
# # Promote student representative
# flask promote-student-rep 12345
#
# # Monitor system
# flask user-stats
# flask users-needing-attention
# flask email-status