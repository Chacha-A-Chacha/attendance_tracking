# models/user.py
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import Index, func
import json

from app import db
from .base import BaseModel

# Association table for many-to-many relationship between users and roles
user_roles = db.Table('user_roles',
                      db.Column('user_id', db.String(36), db.ForeignKey('users.id'), primary_key=True),
                      db.Column('role_id', db.String(36), db.ForeignKey('roles.id'), primary_key=True),
                      db.Column('assigned_at', db.DateTime, default=datetime.utcnow),
                      db.Column('assigned_by', db.String(36), db.ForeignKey('users.id'), nullable=True)
                      )


class Permission:
    """Define system permissions as constants."""

    # Attendance permissions
    VIEW_ATTENDANCE = 'view_attendance'
    MARK_ATTENDANCE = 'mark_attendance'
    EDIT_ATTENDANCE = 'edit_attendance'
    DELETE_ATTENDANCE = 'delete_attendance'
    EXPORT_ATTENDANCE = 'export_attendance'

    # Session management
    VIEW_SESSIONS = 'view_sessions'
    CREATE_SESSIONS = 'create_sessions'
    EDIT_SESSIONS = 'edit_sessions'
    DELETE_SESSIONS = 'delete_sessions'

    # Participant management
    VIEW_PARTICIPANTS = 'view_participants'
    CREATE_PARTICIPANTS = 'create_participants'
    EDIT_PARTICIPANTS = 'edit_participants'
    DELETE_PARTICIPANTS = 'delete_participants'

    # Session reassignment
    VIEW_REASSIGNMENTS = 'view_reassignments'
    REQUEST_REASSIGNMENT = 'request_reassignment'
    APPROVE_REASSIGNMENTS = 'approve_reassignments'
    REJECT_REASSIGNMENTS = 'reject_reassignments'

    # User management
    VIEW_USERS = 'view_users'
    CREATE_USERS = 'create_users'
    EDIT_USERS = 'edit_users'
    DELETE_USERS = 'delete_users'
    MANAGE_ROLES = 'manage_roles'

    # Reports and analytics
    VIEW_REPORTS = 'view_reports'
    GENERATE_REPORTS = 'generate_reports'
    VIEW_ANALYTICS = 'view_analytics'

    # System administration
    ADMIN_ACCESS = 'admin_access'
    SYSTEM_CONFIG = 'system_config'


class RoleType:
    """Define role types as constants."""
    TEACHER = 'teacher'
    CHAPLAIN = 'chaplain'
    STUDENT = 'student'
    STUDENT_REPRESENTATIVE = 'student_representative'
    ADMIN = 'admin'


class Role(BaseModel):
    """Role model for RBAC."""

    __tablename__ = 'roles'

    name = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    permissions = db.Column(db.Text)  # JSON string of permissions
    is_system_role = db.Column(db.Boolean, default=False)  # Prevent deletion of system roles
    is_active = db.Column(db.Boolean, default=True)
    hierarchy_level = db.Column(db.Integer, default=0)  # For role hierarchy (higher = more privileges)

    # Relationships - Fixed with explicit foreign_keys
    users = db.relationship(
        'User',
        secondary=user_roles,
        primaryjoin='Role.id == user_roles.c.role_id',
        secondaryjoin='User.id == user_roles.c.user_id',
        back_populates='roles'
    )

    # Optimized indexing
    __table_args__ = (
        Index('uq_role_name', 'name', unique=True),
        Index('idx_role_active', 'is_active'),
        Index('idx_role_system', 'is_system_role'),
        Index('idx_role_hierarchy', 'hierarchy_level', 'is_active'),

        # Covering index for role listings
        Index('idx_role_listing', 'is_active', 'hierarchy_level',
              postgresql_include=['name', 'display_name']),
    )

    def __repr__(self):
        return f'<Role {self.name}>'

    def get_permissions(self):
        """Get list of permissions for this role."""
        if not self.permissions:
            return []
        try:
            return json.loads(self.permissions)
        except:
            return []

    def set_permissions(self, permissions):
        """Set permissions for this role."""
        self.permissions = json.dumps(permissions)

    def has_permission(self, permission):
        """Check if role has specific permission."""
        return permission in self.get_permissions()

    def add_permission(self, permission):
        """Add a permission to this role."""
        perms = self.get_permissions()
        if permission not in perms:
            perms.append(permission)
            self.set_permissions(perms)

    def remove_permission(self, permission):
        """Remove a permission from this role."""
        perms = self.get_permissions()
        if permission in perms:
            perms.remove(permission)
            self.set_permissions(perms)

    @staticmethod
    def create_default_roles():
        """Create default system roles with appropriate permissions."""
        default_roles = {
            RoleType.TEACHER: {
                'display_name': 'Teacher',
                'description': 'Teaching staff with classroom management privileges',
                'hierarchy_level': 3,
                'permissions': [
                    Permission.VIEW_ATTENDANCE, Permission.MARK_ATTENDANCE, Permission.EDIT_ATTENDANCE,
                    Permission.VIEW_SESSIONS, Permission.EDIT_SESSIONS,
                    Permission.VIEW_PARTICIPANTS, Permission.EDIT_PARTICIPANTS,
                    Permission.VIEW_REASSIGNMENTS, Permission.APPROVE_REASSIGNMENTS, Permission.REJECT_REASSIGNMENTS,
                    Permission.VIEW_REPORTS, Permission.GENERATE_REPORTS
                ]
            },
            RoleType.CHAPLAIN: {
                'display_name': 'Chaplain',
                'description': 'Chaplain with administrative and pastoral privileges',
                'hierarchy_level': 4,
                'permissions': [
                    Permission.VIEW_ATTENDANCE, Permission.MARK_ATTENDANCE, Permission.EDIT_ATTENDANCE,
                    Permission.DELETE_ATTENDANCE,
                    Permission.VIEW_SESSIONS, Permission.CREATE_SESSIONS, Permission.EDIT_SESSIONS,
                    Permission.DELETE_SESSIONS,
                    Permission.VIEW_PARTICIPANTS, Permission.CREATE_PARTICIPANTS, Permission.EDIT_PARTICIPANTS,
                    Permission.VIEW_REASSIGNMENTS, Permission.APPROVE_REASSIGNMENTS, Permission.REJECT_REASSIGNMENTS,
                    Permission.VIEW_USERS, Permission.CREATE_USERS, Permission.EDIT_USERS,
                    Permission.VIEW_REPORTS, Permission.GENERATE_REPORTS, Permission.VIEW_ANALYTICS,
                    Permission.EXPORT_ATTENDANCE
                ]
            },
            RoleType.STUDENT: {
                'display_name': 'Student',
                'description': 'Student with basic access privileges',
                'hierarchy_level': 1,
                'permissions': [
                    Permission.VIEW_ATTENDANCE,  # Own attendance only
                    Permission.REQUEST_REASSIGNMENT,
                    Permission.VIEW_SESSIONS
                ]
            },
            RoleType.STUDENT_REPRESENTATIVE: {
                'display_name': 'Student Representative',
                'description': 'Student representative with elevated privileges',
                'hierarchy_level': 2,
                'permissions': [
                    Permission.VIEW_ATTENDANCE, Permission.MARK_ATTENDANCE,  # Can mark attendance for others
                    Permission.REQUEST_REASSIGNMENT,
                    Permission.VIEW_SESSIONS,
                    Permission.VIEW_PARTICIPANTS,  # Limited view for helping classmates
                    Permission.VIEW_REASSIGNMENTS,  # Can see pending requests
                    Permission.VIEW_REPORTS  # Basic reporting
                ]
            },
            RoleType.ADMIN: {
                'display_name': 'System Administrator',
                'description': 'Full system administration privileges',
                'hierarchy_level': 5,
                'permissions': [perm for perm in dir(Permission) if not perm.startswith('_')]
            }
        }

        for role_name, role_data in default_roles.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(
                    name=role_name,
                    display_name=role_data['display_name'],
                    description=role_data['description'],
                    hierarchy_level=role_data['hierarchy_level'],
                    is_system_role=True
                )
                role.set_permissions(role_data['permissions'])
                db.session.add(role)

        db.session.commit()


class User(UserMixin, BaseModel):
    """User model with RBAC support."""

    __tablename__ = 'users'

    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime)
    login_count = db.Column(db.Integer, default=0)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, default=datetime.now)

    # Link to participant for students
    participant_id = db.Column(db.String(36), db.ForeignKey('participant.id'), nullable=True, index=True)

    # Relationships - Fixed with explicit foreign_keys
    roles = db.relationship(
        'Role',
        secondary=user_roles,
        primaryjoin='User.id == user_roles.c.user_id',
        secondaryjoin='Role.id == user_roles.c.role_id',
        back_populates='users'
    )

    participant = db.relationship('Participant', back_populates='user', uselist=False)

    # Additional relationship for tracking who assigned roles (optional)
    assigned_roles = db.relationship(
        'User',
        secondary=user_roles,
        primaryjoin='User.id == user_roles.c.assigned_by',
        secondaryjoin='User.id == user_roles.c.user_id',
        foreign_keys=[user_roles.c.assigned_by, user_roles.c.user_id],
        viewonly=True
    )

    # Optimized indexing
    __table_args__ = (
        # Unique constraints
        Index('uq_user_username', 'username', unique=True),
        Index('uq_user_email', 'email', unique=True),
        Index('uq_user_participant', 'participant_id', unique=True),

        # Single column indexes for frequent filters
        Index('idx_user_active', 'is_active'),
        Index('idx_user_verified', 'is_verified'),
        Index('idx_user_last_login', 'last_login'),
        Index('idx_user_locked', 'locked_until'),

        # Composite indexes for authentication
        Index('idx_user_auth', 'email', 'is_active'),
        Index('idx_user_login_lookup', 'username', 'is_active'),

        # Covering index for user listings
        Index('idx_user_listing', 'is_active', 'created_at',
              postgresql_include=['username', 'email', 'first_name', 'last_name']),

        # Partial index for active users
        Index('idx_user_active_partial', 'last_login', 'created_at',
              postgresql_where=db.text('is_active = true')),
    )

    def __repr__(self):
        return f'<User {self.username}>'

    def set_password(self, password):
        """Set password hash."""
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, password):
        """Check password against hash."""
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name):
        """Check if user has specific role."""
        return any(role.name == role_name for role in self.roles)

    def has_any_role(self, role_names):
        """Check if user has any of the specified roles."""
        user_roles = [role.name for role in self.roles]
        return any(role in user_roles for role in role_names)

    def has_permission(self, permission):
        """Check if user has specific permission through any role."""
        return any(role.has_permission(permission) for role in self.roles)

    def get_highest_role(self):
        """Get the role with highest hierarchy level."""
        if not self.roles:
            return None
        return max(self.roles, key=lambda role: role.hierarchy_level)

    def can_manage_user(self, target_user):
        """Check if this user can manage another user based on role hierarchy."""
        if not self.has_permission(Permission.EDIT_USERS):
            return False

        my_level = self.get_highest_role()
        target_level = target_user.get_highest_role()

        if not my_level or not target_level:
            return False

        return my_level.hierarchy_level > target_level.hierarchy_level

    def add_role(self, role_name):
        """Add a role to this user."""
        role = Role.query.filter_by(name=role_name).first()
        if role and role not in self.roles:
            self.roles.append(role)

    def remove_role(self, role_name):
        """Remove a role from this user."""
        role = Role.query.filter_by(name=role_name).first()
        if role and role in self.roles:
            self.roles.remove(role)

    def is_student(self):
        """Check if user is a student (has participant record)."""
        return self.participant_id is not None

    def is_staff(self):
        """Check if user is staff (teacher, chaplain, admin)."""
        staff_roles = [RoleType.TEACHER, RoleType.CHAPLAIN, RoleType.ADMIN]
        return self.has_any_role(staff_roles)

    def record_login(self):
        """Record successful login."""
        self.last_login = datetime.utcnow()
        self.login_count += 1
        self.failed_login_attempts = 0
        self.locked_until = None

    def record_failed_login(self):
        """Record failed login attempt."""
        self.failed_login_attempts += 1

        # Lock account after 5 failed attempts for 30 minutes
        if self.failed_login_attempts >= 5:
            from datetime import timedelta
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)

    def is_locked(self):
        """Check if account is currently locked."""
        if not self.locked_until:
            return False
        return datetime.utcnow() < self.locked_until

    def unlock_account(self):
        """Unlock the account."""
        self.locked_until = None
        self.failed_login_attempts = 0

    @property
    def full_name(self):
        """Get user's full name."""
        return f"{self.first_name} {self.last_name}"

    @property
    def primary_role(self):
        """Get the primary role (highest hierarchy) display name."""
        highest_role = self.get_highest_role()
        return highest_role.display_name if highest_role else "No Role"

    def to_dict(self, include_relationships=False):
        """Override to exclude sensitive data."""
        result = super().to_dict(include_relationships=include_relationships)

        # Remove sensitive fields
        result.pop('password_hash', None)
        result.pop('failed_login_attempts', None)
        result.pop('locked_until', None)

        # Add computed fields
        result['full_name'] = self.full_name
        result['primary_role'] = self.primary_role
        result['is_student'] = self.is_student()
        result['is_staff'] = self.is_staff()
        result['is_locked'] = self.is_locked()

        return result
    