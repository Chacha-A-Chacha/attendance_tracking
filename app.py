import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import config_by_name

app = Flask(__name__)
env = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config_by_name[env])
db = SQLAlchemy(app)

# Register blueprints
from controllers.admin import admin_bp
from controllers.check_in import check_in_bp
from controllers.participant import participant_bp

app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(check_in_bp, url_prefix='/check-in')
app.register_blueprint(participant_bp, url_prefix='/participant')

if __name__ == '__main__':
    app.run(debug=True)
    