import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class with all settings as static attributes."""

    # Core configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    # Session timeout settings
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_REFRESH_EACH_REQUEST = True

    # Remember me settings
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # Session timeout for different user roles (in minutes)
    SESSION_TIMEOUT_ADMIN = 480  # 8 hours
    SESSION_TIMEOUT_STAFF = 240  # 4 hours
    SESSION_TIMEOUT_STUDENT = 120  # 2 hours
    SESSION_TIMEOUT_DEFAULT = 60  # 1 hour

    # MySQL connection timeouts
    MYSQL_CONNECT_TIMEOUT = 30
    MYSQL_READ_TIMEOUT = 30
    MYSQL_WRITE_TIMEOUT = 30

    # Database configuration
    base_db_uri = os.environ.get('DATABASE_URL')

    # Fallback to SQLite if no DATABASE_URL is provided
    if not base_db_uri:
        base_db_uri = 'sqlite:///attendance.db'
        print("WARNING: DATABASE_URL not set, falling back to SQLite")

    # Configure database URI
    if base_db_uri.startswith('mysql'):
        # Parse the URI to add connection parameters (but NOT pool_recycle)
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(base_db_uri)

        # Add connection parameters as query string (PyMySQL specific parameters only)
        query_params = {
            'charset': 'utf8mb4',
            'connect_timeout': str(MYSQL_CONNECT_TIMEOUT),
            'read_timeout': str(MYSQL_READ_TIMEOUT),
            'write_timeout': str(MYSQL_WRITE_TIMEOUT),
            # Remove pool_recycle and pool_pre_ping - these are SQLAlchemy options, not PyMySQL options
        }

        query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()])
        new_query = f"{parsed.query}&{query_string}" if parsed.query else query_string

        # Reconstruct the URI
        SQLALCHEMY_DATABASE_URI = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    else:
        SQLALCHEMY_DATABASE_URI = base_db_uri

    # Disable track modifications for performance
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # SQLAlchemy engine options (pool_recycle goes here, not in connection string)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 3600,  # Recycle connections after 1 hour
        "pool_pre_ping": True,  # Check connection health before use
        "pool_size": 10,
        "max_overflow": 20,
        "connect_args": {
            "connect_timeout": 30,  # 30 second connection timeout
            "read_timeout": 30,  # 30 second read timeout
            "write_timeout": 30,  # 30 second write timeout
        }
    }

    # Connection retry settings
    DB_CONNECTION_RETRIES = 3
    DB_RETRY_DELAY = 2  # seconds

    # Health monitoring
    ENABLE_DB_HEALTH_MONITOR = True
    DB_HEALTH_CHECK_INTERVAL = 300  # 5 minutes

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # Directory configuration
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    QR_CODE_FOLDER = os.path.join(BASE_DIR, 'static/qrcodes')

    # Specific upload folders
    REGISTRATION_RECEIPTS_FOLDER = os.path.join(UPLOAD_FOLDER, 'registration_receipts')
    GRADUATION_RECEIPTS_FOLDER = os.path.join(UPLOAD_FOLDER, 'graduation_receipts')
    GENERAL_UPLOADS_FOLDER = os.path.join(UPLOAD_FOLDER, 'general')

    # File upload configuration
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    MAX_RECEIPT_SIZE = 5 * 1024 * 1024  # 5MB for receipts

    # File extensions by category
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}  # For data imports
    RECEIPT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}  # For receipt uploads
    DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}  # For documents
    ALL_ALLOWED_EXTENSIONS = ALLOWED_EXTENSIONS | RECEIPT_EXTENSIONS | DOCUMENT_EXTENSIONS

    # Site settings
    SITE_NAME = 'Programming Course'
    CONTACT_EMAIL = 'info@jaribu.org'

    # Session settings
    DEFAULT_SESSION_CAPACITY = 30
    SESSION_BREAK_TIME = '12:30pm - 1:00pm'
    CONSECUTIVE_ABSENCE_LIMIT = 3

    # Time sessions
    SATURDAY_SESSIONS = [
        '9:00am - 12:00pm',
        '1:00pm - 4:00pm'
    ]

    SUNDAY_SESSIONS = [
        '8:00am - 10:00am',
        '2:00pm - 4:00pm'
    ]

    # Classroom settings
    LAPTOP_CLASSROOM = '205'
    NO_LAPTOP_CLASSROOM = '203'
    AUTO_ASSIGN_BY_LAPTOP = True

    SESSION_CAPACITY = {
        '205': 50,  # Regular classroom (laptop classroom)
        '203': 45  # Computer Lab (non-laptop)
    }

    # Email configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'calex2607@gmail.com')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '***********')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Programming Course <test-info@jaribu.org>')

    # Create necessary directories
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(QR_CODE_FOLDER, exist_ok=True)
    os.makedirs(REGISTRATION_RECEIPTS_FOLDER, exist_ok=True)
    os.makedirs(GRADUATION_RECEIPTS_FOLDER, exist_ok=True)
    os.makedirs(GENERAL_UPLOADS_FOLDER, exist_ok=True)

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
    SQLALCHEMY_ECHO = os.environ.get('SQL_DEBUG', 'false').lower() == 'true'


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

    # Override for testing
    DEFAULT_SESSION_CAPACITY = 10  # Smaller capacity for testing
    CONSECUTIVE_ABSENCE_LIMIT = 2  # Lower limit for testing


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
