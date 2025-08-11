import os
from datetime import timedelta


class Config:
    """Base configuration class with database-driven settings."""

    # Core configuration - keep these in code for security and bootstrap
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    DEBUG = os.environ.get('FLASK_DEBUG') or True

    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///attendance.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # Directory configuration - create once
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    QR_CODE_FOLDER = os.path.join(BASE_DIR, 'static/qrcodes')

    # Specific upload folders
    REGISTRATION_RECEIPTS_FOLDER = os.path.join(UPLOAD_FOLDER, 'registration_receipts')
    GRADUATION_RECEIPTS_FOLDER = os.path.join(UPLOAD_FOLDER, 'graduation_receipts')
    GENERAL_UPLOADS_FOLDER = os.path.join(UPLOAD_FOLDER, 'general')

    # File extensions by category
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}  # For data imports
    RECEIPT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}  # For receipt uploads
    DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}  # For documents

    # Combined allowed extensions
    ALL_ALLOWED_EXTENSIONS = ALLOWED_EXTENSIONS | RECEIPT_EXTENSIONS | DOCUMENT_EXTENSIONS

    # Create necessary directories
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(QR_CODE_FOLDER, exist_ok=True)
    os.makedirs(REGISTRATION_RECEIPTS_FOLDER, exist_ok=True)
    os.makedirs(GRADUATION_RECEIPTS_FOLDER, exist_ok=True)
    os.makedirs(GENERAL_UPLOADS_FOLDER, exist_ok=True)

    # Database configuration fallbacks (used when DB is not available)
    _FALLBACK_CONFIG = {
        'general': {
            'site_name': 'Programming Course',
            'contact_email': 'info@jaribu.org',
            'max_upload_size': 16 * 1024 * 1024,  # 16MB
            'max_receipt_size': 5 * 1024 * 1024,  # 5MB for receipts
            'allowed_receipt_formats': 'png,jpg,jpeg,pdf,webp',
        },
        'sessions': {
            'default_session_capacity': 30,
            'session_break_time': '12:30pm - 1:00pm',
            'consecutive_absence_limit': 3,
        },
        'classrooms': {
            'laptop_classroom_default': '205',
            'non_laptop_classroom_default': '203',
            'auto_assign_by_laptop': True,
        },
        'email': {
            'mail_server': 'smtp.gmail.com',
            'mail_port': 465,
            'mail_use_tls': False,
            'mail_use_ssl': True,
            'mail_username': os.environ.get('MAIL_USERNAME', 'calex2607@gmail.com'),
            'mail_password': os.environ.get('MAIL_PASSWORD', '***********'),
            'mail_default_sender': os.environ.get('MAIL_DEFAULT_SENDER', 'Programming Course <test-info@jaribu.org>'),
        }
    }

    @staticmethod
    def get_db_config(category, key, default=None):
        """Get configuration from database with fallback."""
        try:
            # Import here to avoid circular imports
            from models.system_config import SystemConfiguration
            return SystemConfiguration.get_config(category, key, default)
        except Exception:
            # Database not available or table doesn't exist yet
            fallback = Config._FALLBACK_CONFIG.get(category, {})
            return fallback.get(key, default)

    # Dynamic properties that fetch from database
    @property
    def SITE_NAME(self):
        """Site name from database configuration."""
        return self.get_db_config('general', 'site_name', 'Programming Course')

    @property
    def CONTACT_EMAIL(self):
        """Contact email from database configuration."""
        return self.get_db_config('general', 'contact_email', 'info@jaribu.org')

    @property
    def MAX_CONTENT_LENGTH(self):
        """Maximum upload size from database configuration."""
        return self.get_db_config('general', 'max_upload_size', 16 * 1024 * 1024)

    @property
    def MAX_RECEIPT_SIZE(self):
        """Maximum receipt upload size from database configuration."""
        return self.get_db_config('general', 'max_receipt_size', 5 * 1024 * 1024)

    @property
    def ALLOWED_RECEIPT_FORMATS(self):
        """Allowed receipt file formats from database configuration."""
        formats = self.get_db_config('general', 'allowed_receipt_formats', 'png,jpg,jpeg,pdf,webp')
        return set(formats.split(',')) if isinstance(formats, str) else formats

    # Session configuration properties
    @property
    def DEFAULT_SESSION_CAPACITY(self):
        """Default session capacity from database."""
        return self.get_db_config('sessions', 'default_session_capacity', 30)

    @property
    def SESSION_BREAK_TIME(self):
        """Session break time from database."""
        return self.get_db_config('sessions', 'session_break_time', '12:30pm - 1:00pm')

    @property
    def CONSECUTIVE_ABSENCE_LIMIT(self):
        """Consecutive absence limit before account deactivation."""
        return self.get_db_config('sessions', 'consecutive_absence_limit', 3)

    # Classroom configuration properties
    @property
    def LAPTOP_CLASSROOM(self):
        """Default laptop classroom from database."""
        return self.get_db_config('classrooms', 'laptop_classroom_default', '205')

    @property
    def NO_LAPTOP_CLASSROOM(self):
        """Default non-laptop classroom from database."""
        return self.get_db_config('classrooms', 'non_laptop_classroom_default', '203')

    @property
    def AUTO_ASSIGN_BY_LAPTOP(self):
        """Whether to auto-assign participants by laptop availability."""
        return self.get_db_config('classrooms', 'auto_assign_by_laptop', True)

    # Email configuration properties
    @property
    def MAIL_SERVER(self):
        """Mail server from database or environment."""
        return self.get_db_config('email', 'mail_server',
                                  os.environ.get('MAIL_SERVER', 'smtp.gmail.com'))

    @property
    def MAIL_PORT(self):
        """Mail port from database or environment."""
        return self.get_db_config('email', 'mail_port',
                                  int(os.environ.get('MAIL_PORT', 465)))

    @property
    def MAIL_USE_TLS(self):
        """Mail TLS setting from database."""
        return self.get_db_config('email', 'mail_use_tls', False)

    @property
    def MAIL_USE_SSL(self):
        """Mail SSL setting from database."""
        return self.get_db_config('email', 'mail_use_ssl', True)

    @property
    def MAIL_USERNAME(self):
        """Mail username from environment."""
        return os.environ.get('MAIL_USERNAME', 'calex2607@gmail.com')

    @property
    def MAIL_PASSWORD(self):
        """Mail password from environment."""
        return os.environ.get('MAIL_PASSWORD', '***********')

    @property
    def MAIL_DEFAULT_SENDER(self):
        """Mail default sender from environment."""
        return os.environ.get('MAIL_DEFAULT_SENDER', 'Programming Course <test-info@jaribu.org>')

    # Dynamic methods for fetching sessions and classrooms
    def get_active_sessions(self, day=None):
        """Get active sessions from database."""
        try:
            from models.session import Session
            query = Session.query.filter_by(is_active=True)
            if day:
                query = query.filter_by(day=day)
            return query.order_by(Session.time_slot).all()
        except Exception:
            # Fallback to hardcoded sessions if database not available
            return self._get_fallback_sessions(day)

    def _get_fallback_sessions(self, day=None):
        """Fallback sessions when database is not available."""
        sessions = [
            '8:00am - 9:30am',
            '9:30am - 11:00am',
            '11:00am - 12:30pm',
            '1:00pm - 2:30pm',
            '2:30pm - 4:00pm',
            '4:00pm - 5:30pm'
        ]

        if day:
            return [{'day': day, 'time_slot': slot} for slot in sessions]
        else:
            result = []
            for d in ['Saturday', 'Sunday']:
                result.extend([{'day': d, 'time_slot': slot} for slot in sessions])
            return result

    def get_active_classrooms(self):
        """Get active classrooms from database."""
        try:
            from models.classroom import Classroom
            return Classroom.get_active_classrooms()
        except Exception:
            # Fallback to hardcoded classrooms
            return [
                {
                    'classroom_number': '205',
                    'name': 'Computer Lab',
                    'capacity': 50,
                    'has_laptop_support': True
                },
                {
                    'classroom_number': '203',
                    'name': 'Regular Classroom',
                    'capacity': 45,
                    'has_laptop_support': False
                }
            ]

    def get_session_capacity(self, classroom_number=None):
        """Get session capacity for specific classroom or default."""
        try:
            if classroom_number:
                from models.classroom import Classroom
                classroom = Classroom.query.filter_by(classroom_number=classroom_number).first()
                return classroom.capacity if classroom else self.DEFAULT_SESSION_CAPACITY
            return self.DEFAULT_SESSION_CAPACITY
        except Exception:
            # Fallback capacity mapping
            fallback_capacities = {
                '205': 50,
                '203': 45
            }
            return fallback_capacities.get(classroom_number, 30)

    # Legacy properties for backward compatibility
    @property
    def SATURDAY_SESSIONS(self):
        """Legacy Saturday sessions list for backward compatibility."""
        sessions = self.get_active_sessions('Saturday')
        return [session.time_slot if hasattr(session, 'time_slot') else session['time_slot']
                for session in sessions]

    @property
    def SUNDAY_SESSIONS(self):
        """Legacy Sunday sessions list for backward compatibility."""
        sessions = self.get_active_sessions('Sunday')
        return [session.time_slot if hasattr(session, 'time_slot') else session['time_slot']
                for session in sessions]

    @property
    def SESSION_CAPACITY(self):
        """Legacy session capacity mapping for backward compatibility."""
        try:
            classrooms = self.get_active_classrooms()
            if hasattr(classrooms[0], 'classroom_number'):
                # Database objects
                return {c.classroom_number: c.capacity for c in classrooms}
            else:
                # Fallback dictionaries
                return {c['classroom_number']: c['capacity'] for c in classrooms}
        except Exception:
            return {'205': 50, '203': 45}

    # File upload utilities
    @staticmethod
    def allowed_file(filename, file_type='general'):
        """Check if file extension is allowed for specific upload type."""
        if not filename or '.' not in filename:
            return False

        ext = filename.rsplit('.', 1)[1].lower()

        if file_type == 'receipt':
            return ext in Config.RECEIPT_EXTENSIONS
        elif file_type == 'document':
            return ext in Config.DOCUMENT_EXTENSIONS
        elif file_type == 'data':
            return ext in Config.ALLOWED_EXTENSIONS
        else:  # general
            return ext in Config.ALL_ALLOWED_EXTENSIONS

    @staticmethod
    def get_upload_path(upload_type, filename=None):
        """Get appropriate upload path for different file types."""
        paths = {
            'registration_receipt': Config.REGISTRATION_RECEIPTS_FOLDER,
            'graduation_receipt': Config.GRADUATION_RECEIPTS_FOLDER,
            'general': Config.GENERAL_UPLOADS_FOLDER,
            'qr_code': Config.QR_CODE_FOLDER
        }

        base_path = paths.get(upload_type, Config.GENERAL_UPLOADS_FOLDER)

        if filename:
            return os.path.join(base_path, filename)
        return base_path

    @staticmethod
    def generate_receipt_filename(prefix, student_id, original_filename):
        """Generate standardized receipt filename."""
        import uuid
        from datetime import datetime

        # Get file extension
        ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'pdf'

        # Generate filename: prefix_studentid_timestamp_uuid.ext
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]

        return f"{prefix}_{student_id}_{timestamp}_{unique_id}.{ext}"


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

    # Development-specific overrides
    SQLALCHEMY_ECHO = True  # Log SQL queries in development


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

    # Ensure secret key is set in production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production")

    # Use production database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable must be set in production")

    # Production security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

    # Override properties for testing
    @property
    def DEFAULT_SESSION_CAPACITY(self):
        return 10  # Smaller capacity for testing

    @property
    def CONSECUTIVE_ABSENCE_LIMIT(self):
        return 2  # Lower limit for testing


# Configuration dictionary
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}


# Helper function to get current configuration
def get_config():
    """Get current configuration instance."""
    config_name = os.environ.get('FLASK_CONFIG', 'development')
    return config_by_name[config_name]()


# Configuration initialization helper
def init_app_config(app):
    """Initialize app with configuration and set up database-driven settings."""
    config_name = os.environ.get('FLASK_CONFIG', 'development')
    app.config.from_object(config_by_name[config_name])

    # Store config instance for easy access
    app.config_instance = config_by_name[config_name]()

    return app.config_instance


# Example usage for file uploads:
"""
from config import Config

# Check if uploaded file is valid receipt
if Config.allowed_file(filename, 'receipt'):
    # Generate standardized filename
    receipt_filename = Config.generate_receipt_filename(
        'registration', 
        student.unique_id, 
        uploaded_file.filename
    )

    # Get full upload path
    upload_path = Config.get_upload_path('registration_receipt', receipt_filename)

    # Save file
    uploaded_file.save(upload_path)

    # Store relative path in database
    relative_path = f"registration_receipts/{receipt_filename}"
    student_enrollment.receipt_upload_path = relative_path

# Example for graduation receipts
if Config.allowed_file(graduation_receipt.filename, 'receipt'):
    receipt_filename = Config.generate_receipt_filename(
        'graduation',
        participant.unique_id,
        graduation_receipt.filename
    )

    upload_path = Config.get_upload_path('graduation_receipt', receipt_filename)
    graduation_receipt.save(upload_path)

    relative_path = f"graduation_receipts/{receipt_filename}"
    participant.graduation_fee_receipt_upload_path = relative_path
"""