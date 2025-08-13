# services/config_service.py
from app.models.classroom import Classroom
from app.models.session import Session
from app.models.system_config import SystemConfiguration, ConfigCategory
from app.extensions import db


class ConfigurationService:
    """Service for managing system configuration."""

    @staticmethod
    def initialize_default_classrooms():
        """Initialize default classrooms from config."""
        # Laptop classroom
        laptop_classroom = Classroom.query.filter_by(classroom_number='205').first()
        if not laptop_classroom:
            laptop_classroom = Classroom(
                classroom_number='205',
                name='Computer Lab',
                capacity=50,
                has_laptop_support=True,
                description='Classroom equipped with computers and laptop support',
                location='Second Floor'
            )
            db.session.add(laptop_classroom)

        # Non-laptop classroom
        non_laptop_classroom = Classroom.query.filter_by(classroom_number='203').first()
        if not non_laptop_classroom:
            non_laptop_classroom = Classroom(
                classroom_number='203',
                name='Regular Classroom',
                capacity=45,
                has_laptop_support=False,
                description='Standard classroom without laptop requirements',
                location='Second Floor'
            )
            db.session.add(non_laptop_classroom)

        db.session.commit()
        return [laptop_classroom, non_laptop_classroom]

    @staticmethod
    def initialize_default_sessions():
        """Initialize default sessions from config."""
        saturday_slots = [
            '8:00am - 9:30am',
            '9:30am - 11:00am',
            '11:00am - 12:30pm',
            '1:00pm - 2:30pm',
            '2:30pm - 4:00pm',
            '4:00pm - 5:30pm'
        ]

        sunday_slots = [
            '8:00am - 9:30am',
            '9:30am - 11:00am',
            '11:00am - 12:30pm',
            '1:00pm - 2:30pm',
            '2:30pm - 4:00pm',
            '4:00pm - 5:30pm'
        ]

        created_sessions = []

        # Create Saturday sessions
        for slot in saturday_slots:
            existing = Session.query.filter_by(day='Saturday', time_slot=slot).first()
            if not existing:
                session = Session(
                    day='Saturday',
                    time_slot=slot,
                    max_capacity=30,
                    is_active=True
                )
                db.session.add(session)
                created_sessions.append(session)

        # Create Sunday sessions
        for slot in sunday_slots:
            existing = Session.query.filter_by(day='Sunday', time_slot=slot).first()
            if not existing:
                session = Session(
                    day='Sunday',
                    time_slot=slot,
                    max_capacity=30,
                    is_active=True
                )
                db.session.add(session)
                created_sessions.append(session)

        db.session.commit()
        return created_sessions

    @staticmethod
    def initialize_default_configs():
        """Initialize default system configurations."""
        configs = [
            # General settings
            (ConfigCategory.GENERAL, 'site_name', 'Programming Course', 'string', 'Site name', True),
            (ConfigCategory.GENERAL, 'contact_email', 'info@jaribu.org', 'string', 'Contact email', True),
            (ConfigCategory.GENERAL, 'max_upload_size', '16777216', 'int', 'Max upload size in bytes', False),

            # Session settings
            (ConfigCategory.SESSIONS, 'default_session_capacity', '30', 'int', 'Default session capacity', False),
            (ConfigCategory.SESSIONS, 'session_break_time', '12:30pm - 1:00pm', 'string', 'Break time between sessions',
             True),
            (ConfigCategory.SESSIONS, 'consecutive_absence_limit', '3', 'int',
             'Max consecutive absences before deactivation', False),

            # Classroom settings
            (ConfigCategory.CLASSROOMS, 'laptop_classroom_default', '205', 'string', 'Default laptop classroom', False),
            (ConfigCategory.CLASSROOMS, 'non_laptop_classroom_default', '203', 'string', 'Default non-laptop classroom',
             False),
            (ConfigCategory.CLASSROOMS, 'auto_assign_by_laptop', 'true', 'bool',
             'Auto-assign participants to classrooms based on laptop availability', False),

            # Email settings
            (ConfigCategory.EMAIL, 'mail_server', 'smtp.gmail.com', 'string', 'SMTP server', False),
            (ConfigCategory.EMAIL, 'mail_port', '465', 'int', 'SMTP port', False),
            (ConfigCategory.EMAIL, 'mail_use_ssl', 'true', 'bool', 'Use SSL for email', False),
        ]

        for category, key, value, data_type, description, is_public in configs:
            existing = SystemConfiguration.query.filter_by(category=category, key=key).first()
            if not existing:
                config = SystemConfiguration(
                    category=category,
                    key=key,
                    value=value,
                    data_type=data_type,
                    description=description,
                    is_public=is_public
                )
                db.session.add(config)

        db.session.commit()

    @staticmethod
    def get_classroom_for_participant(has_laptop):
        """Get appropriate classroom for participant based on laptop availability."""
        auto_assign = SystemConfiguration.get_config(ConfigCategory.CLASSROOMS, 'auto_assign_by_laptop', True)

        if not auto_assign:
            # Return default classroom if auto-assignment is disabled
            default_classroom = SystemConfiguration.get_config(ConfigCategory.CLASSROOMS, 'laptop_classroom_default',
                                                               '205')
            return Classroom.query.filter_by(classroom_number=default_classroom).first()

        if has_laptop:
            classroom = Classroom.get_laptop_classroom()
        else:
            classroom = Classroom.get_non_laptop_classroom()

        # Check capacity
        if classroom and not classroom.is_at_capacity():
            return classroom

        # If at capacity, find any available classroom
        for alt_classroom in Classroom.get_active_classrooms():
            if not alt_classroom.is_at_capacity():
                return alt_classroom

        # Return the preferred classroom even if at capacity (manual intervention needed)
        return classroom

    @staticmethod
    def sync_config_to_database():
        """Sync configuration from files to database."""
        ConfigurationService.initialize_default_classrooms()
        ConfigurationService.initialize_default_sessions()
        ConfigurationService.initialize_default_configs()


# CLI commands for configuration management
import click
from flask.cli import with_appcontext


@click.command()
@with_appcontext
def init_config():
    """Initialize default configuration."""
    ConfigurationService.sync_config_to_database()
    click.echo("Configuration initialized successfully!")


@click.command()
@click.option('--category', required=True, help='Configuration category')
@click.option('--key', required=True, help='Configuration key')
@click.option('--value', required=True, help='Configuration value')
@click.option('--type', 'data_type', default='string', help='Data type (string, int, float, bool, json)')
@with_appcontext
def set_config(category, key, value, data_type):
    """Set a configuration value."""
    SystemConfiguration.set_config(category, key, value, data_type)
    click.echo(f"Set {category}.{key} = {value}")


@click.command()
@click.option('--category', help='Filter by category')
@with_appcontext
def list_config(category):
    """List configuration values."""
    if category:
        configs = SystemConfiguration.query.filter_by(category=category).all()
    else:
        configs = SystemConfiguration.query.all()

    for config in configs:
        click.echo(f"{config.category}.{config.key} = {config.value} ({config.data_type})")


def register_config_commands(app):
    """Register configuration management commands."""
    app.cli.add_command(init_config)
    app.cli.add_command(set_config)
    app.cli.add_command(list_config)
