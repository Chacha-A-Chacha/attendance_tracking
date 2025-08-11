# models/classroom.py
from app import db
from sqlalchemy import Index
from .base import BaseModel


class Classroom(BaseModel):
    """Model for managing classrooms and their configurations."""

    __tablename__ = 'classroom'

    classroom_number = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=30)
    has_laptop_support = db.Column(db.Boolean, default=False, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    location = db.Column(db.String(255), nullable=True)
    equipment_notes = db.Column(db.Text, nullable=True)

    # Optimized indexing
    __table_args__ = (
        Index('uq_classroom_number', 'classroom_number', unique=True),
        Index('idx_classroom_active', 'is_active'),
        Index('idx_classroom_has_laptop', 'has_laptop_support'),
        Index('idx_classroom_capacity', 'capacity'),

        # Composite index for assignment queries
        Index('idx_classroom_active_laptop', 'is_active', 'has_laptop_support'),

        # Covering index for classroom listings
        Index('idx_classroom_listing', 'is_active', 'has_laptop_support',
              postgresql_include=['classroom_number', 'name', 'capacity']),
    )

    @property
    def display_name(self):
        """Get formatted display name."""
        return f"Room {self.classroom_number} - {self.name}"

    def get_participants_count(self):
        """Get current number of participants assigned to this classroom."""
        from .participant import Participant
        return Participant.query.filter_by(classroom=self.classroom_number, is_active=True).count()

    def is_at_capacity(self):
        """Check if classroom is at capacity."""
        return self.get_participants_count() >= self.capacity

    def get_available_spots(self):
        """Get number of available spots."""
        return max(0, self.capacity - self.get_participants_count())

    @classmethod
    def get_laptop_classroom(cls):
        """Get the primary laptop-enabled classroom."""
        return cls.query.filter_by(has_laptop_support=True, is_active=True).first()

    @classmethod
    def get_non_laptop_classroom(cls):
        """Get the primary non-laptop classroom."""
        return cls.query.filter_by(has_laptop_support=False, is_active=True).first()

    @classmethod
    def get_active_classrooms(cls):
        """Get all active classrooms."""
        return cls.query.filter_by(is_active=True).order_by(cls.classroom_number).all()

    def to_dict(self, include_relationships=False):
        """Override to include computed fields."""
        result = super().to_dict(include_relationships=include_relationships)

        # Add computed fields
        result['display_name'] = self.display_name
        result['participants_count'] = self.get_participants_count()
        result['available_spots'] = self.get_available_spots()
        result['is_at_capacity'] = self.is_at_capacity()

        return result

    def __repr__(self):
        return f'<Classroom {self.classroom_number} - {self.name}>'
