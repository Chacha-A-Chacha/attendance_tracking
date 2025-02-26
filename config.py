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
    
    # Time sessions
    SATURDAY_SESSIONS = [
        '8.00am - 9.30am',
        '10.00am - 11.30am',
        '12.00pm - 1.30pm',
        '2.00pm - 3.30pm',
        '4.00pm - 5.30pm'
    ]
    
    SUNDAY_SESSIONS = [
        '8.00am - 9.30am',
        '10.00am - 11.30am',
        '12.00pm - 1.30pm',
        '2.00pm - 3.30pm',
        '4.00pm - 5.30pm'
    ]
    
    # Classrooms
    LAPTOP_CLASSROOM = '203'
    NO_LAPTOP_CLASSROOM = '204'
    
    SESSION_CAPACITY = {
        '203': 30,  # Laptop classroom max capacity
        '204': 40   # Non-laptop classroom max capacity
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
