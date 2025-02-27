import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import config_by_name

# Initialize extensions
db = SQLAlchemy()

def create_app(config_name=None):
    """Application factory function"""
    # Create Flask app
    app = Flask(__name__)
    
    # Load configuration
    config_name = config_name or os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config_by_name[config_name])
    
    # Initialize extensions with app
    db.init_app(app)
    
    # Import and register blueprints
    from controllers.admin import admin_bp
    from controllers.check_in import check_in_bp
    from controllers.participant import participant_bp
    
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(check_in_bp, url_prefix='/check-in')
    app.register_blueprint(participant_bp, url_prefix='/participant')
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Initialize default data if needed
        initialize_default_data(app)
    
    return app

def initialize_default_data(app):
    """Initialize system with default data if needed"""
    from models import Session
    
    # Only proceed if no sessions exist (fresh installation)
    with app.app_context():
        if Session.query.count() == 0:
            from services.importer import init_sessions
            init_sessions()
            
            # Check if default data file exists
            data_path = os.path.join(app.root_path, 'data', 'sessions_data.xlsx')
            if os.path.exists(data_path):
                app.logger.info(f"Importing default data from {data_path}")
                from services.importer import import_spreadsheet
                import_spreadsheet(data_path)
            else:
                app.logger.info("No default data file found at data/participants.csv")

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0')
