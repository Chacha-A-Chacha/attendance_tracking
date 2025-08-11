# models/system_config.py
from app import db
from sqlalchemy import Index
from .base import BaseModel
import json


class ConfigCategory:
    """Configuration categories."""
    GENERAL = 'general'
    SESSIONS = 'sessions'
    CLASSROOMS = 'classrooms'
    EMAIL = 'email'
    UPLOADS = 'uploads'
    SECURITY = 'security'


class SystemConfiguration(BaseModel):
    """Model for storing system-wide configuration settings."""

    __tablename__ = 'system_configuration'

    category = db.Column(db.String(50), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=True)
    data_type = db.Column(db.String(20), default='string', nullable=False)  # string, int, float, bool, json
    description = db.Column(db.Text, nullable=True)
    is_public = db.Column(db.Boolean, default=False)  # Can be exposed to frontend
    is_editable = db.Column(db.Boolean, default=True)  # Can be modified via admin interface
    default_value = db.Column(db.Text, nullable=True)

    # Optimized indexing
    __table_args__ = (
        Index('uq_config_category_key', 'category', 'key', unique=True),
        Index('idx_config_category', 'category'),
        Index('idx_config_public', 'is_public'),
        Index('idx_config_editable', 'is_editable'),

        # Covering index for config retrieval
        Index('idx_config_retrieval', 'category', 'key',
              postgresql_include=['value', 'data_type']),
    )

    def get_typed_value(self):
        """Get value converted to appropriate Python type."""
        if self.value is None:
            return None

        try:
            if self.data_type == 'int':
                return int(self.value)
            elif self.data_type == 'float':
                return float(self.value)
            elif self.data_type == 'bool':
                return self.value.lower() in ('true', '1', 'yes', 'on')
            elif self.data_type == 'json':
                return json.loads(self.value)
            else:  # string
                return self.value
        except (ValueError, json.JSONDecodeError):
            return self.default_value

    def set_typed_value(self, value):
        """Set value with automatic type conversion."""
        if self.data_type == 'json':
            self.value = json.dumps(value)
        else:
            self.value = str(value)

    @classmethod
    def get_config(cls, category, key, default=None):
        """Get a configuration value."""
        config = cls.query.filter_by(category=category, key=key).first()
        if config:
            return config.get_typed_value()
        return default

    @classmethod
    def set_config(cls, category, key, value, data_type='string', description=None):
        """Set a configuration value."""
        config = cls.query.filter_by(category=category, key=key).first()
        if not config:
            config = cls(category=category, key=key, data_type=data_type, description=description)
            db.session.add(config)

        config.set_typed_value(value)
        db.session.commit()
        return config

    @classmethod
    def get_category_configs(cls, category):
        """Get all configurations for a category."""
        configs = cls.query.filter_by(category=category).all()
        return {config.key: config.get_typed_value() for config in configs}

    @classmethod
    def get_public_configs(cls):
        """Get all public configurations for frontend use."""
        configs = cls.query.filter_by(is_public=True).all()
        result = {}
        for config in configs:
            if config.category not in result:
                result[config.category] = {}
            result[config.category][config.key] = config.get_typed_value()
        return result

    def __repr__(self):
        return f'<SystemConfiguration {self.category}.{self.key}>'
