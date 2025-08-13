# models/base.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid
from app.extensions import db


class BaseModel(db.Model):
    """Base model class with common functionality."""

    __abstract__ = True

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def to_dict(self, include_relationships=False):
        """Convert model instance to dictionary."""
        result = {}

        # Include all columns
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                result[column.name] = value.isoformat()
            else:
                result[column.name] = value

        # Optionally include relationships
        if include_relationships:
            for relationship in self.__mapper__.relationships:
                try:
                    rel_value = getattr(self, relationship.key)
                    if rel_value is None:
                        result[relationship.key] = None
                    elif hasattr(rel_value, '__iter__') and not isinstance(rel_value, str):
                        # One-to-many or many-to-many relationship
                        result[relationship.key] = [item.to_dict() for item in rel_value]
                    else:
                        # One-to-one or many-to-one relationship
                        result[relationship.key] = rel_value.to_dict()
                except:
                    # Skip relationships that can't be loaded
                    pass

        return result

    def from_dict(self, data):
        """Update model instance from dictionary."""
        for field, value in data.items():
            if hasattr(self, field) and field not in ['id', 'created_at', 'updated_at']:
                setattr(self, field, value)

    def __getitem__(self, key):
        """Enable dict-like access: model['field']"""
        return getattr(self, key)

    def __setitem__(self, key, value):
        """Enable dict-like assignment: model['field'] = value"""
        setattr(self, key, value)

    def __contains__(self, key):
        """Enable 'in' operator: 'field' in model"""
        return hasattr(self, key)

    def save(self):
        """Save the model instance."""
        db.session.add(self)
        db.session.commit()
        return self

    def delete(self):
        """Delete the model instance."""
        db.session.delete(self)
        db.session.commit()
