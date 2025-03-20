import os
from datetime import timedelta


class Config:
    # Base configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    DEBUG = os.environ.get('FLASK_DEBUG') or True

    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///attendance.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload size

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # QR Code configuration
    QR_CODE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/qrcodes')

    # Saturday Sessions
    SATURDAY_SESSIONS = [
        '8:00am - 9:30am',  # Session 1
        '9:30am - 11:00am',  # Session 2
        '11:00am - 12:30pm',  # Session 3
        # Break (12:30pm - 1:00pm)
        '1:00pm - 2:30pm',  # Session 4
        '2:30pm - 4:00pm',  # Session 5
        '4:00pm - 5:30pm'  # Session 6
    ]

    # Sunday Sessions
    SUNDAY_SESSIONS = [
        '8:00am - 9:30am',  # Session 1
        '9:30am - 11:00am',  # Session 2
        '11:00am - 12:30pm',  # Session 3
        # Break (12:30pm - 1:00pm)
        '1:00pm - 2:30pm',  # Session 4
        '2:30pm - 4:00pm',  # Session 5
        '4:00pm - 5:30pm'  # Session 6
    ]

    # Classrooms
    LAPTOP_CLASSROOM = '205'
    NO_LAPTOP_CLASSROOM = '203'

    SESSION_CAPACITY = {
        '205': 50,  # Laptop classroom max capacity
        '203': 45  # Non-laptop classroom max capacity
    }

    # Create necessary directories if they don't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(QR_CODE_FOLDER, exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SECRET_KEY = os.environ.get('SECRET_KEY')  # Must be set in production

    # Use a production database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Configuration dictionary
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}
