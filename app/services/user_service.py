# services/user_service.py
"""
Optimized User Service for user management operations.
Handles user creation, role management, and user queries with optimized database operations.
"""

import logging
import secrets
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload, selectinload, contains_eager
from sqlalchemy import and_, or_, func, exists, text, case
from sqlalchemy.exc import IntegrityError

from app.models.user import User, Role, RoleType, Permission
from app.models.participant import Participant
from app.models.enrollment import StudentEnrollment
from app.extensions import db
from app.services.auth_service import AuthService


class UserService:
    """Optimized service class for user management operations."""

    @staticmethod
    def create_user(username, email, first_name, last_name, password=None, roles=None,
                    send_welcome_email=True, created_by_user_id=None):
        """
        Create a new user with specified roles (for non-participant users).

        Args:
            username: Unique username
            email: Email address
            first_name: First name
            last_name: Last name
            password: Password (generated if not provided)
            roles: List of role names to assign
            send_welcome_email: Whether to send welcome email
            created_by_user_id: ID of user creating this account

        Returns:
            tuple: (user: User, password: str, task_id: str|None)
        """
        logger = logging.getLogger('user_service')

        try:
            # Optimized existence checks using scalar subqueries
            username_exists = db.session.query(
                db.session.query(User.id).filter_by(username=username).exists()
            ).scalar()

            if username_exists:
                raise ValueError(f"Username '{username}' already exists")

            email_exists = db.session.query(
                db.session.query(User.id).filter_by(email=email).exists()
            ).scalar()

            if email_exists:
                raise ValueError(f"Email '{email}' already exists")

            # Generate secure password if not provided
            if not password:
                password = secrets.token_urlsafe(12)

            # Create user
            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_verified=True,  # Staff users are pre-verified
                is_active=True
            )
            user.set_password(password)

            # Assign roles if provided - optimized role loading
            if roles:
                role_objects = (
                    db.session.query(Role)
                    .filter(Role.name.in_(roles))
                    .all()
                )

                if len(role_objects) != len(roles):
                    found_roles = [r.name for r in role_objects]
                    missing_roles = set(roles) - set(found_roles)
                    raise ValueError(f"Invalid roles: {', '.join(missing_roles)}")

                user.roles = role_objects

            db.session.add(user)
            db.session.commit()

            # Send welcome email if requested
            task_id = None
            if send_welcome_email:
                try:
                    success, task_id = AuthService.send_welcome_email(user.id, password)
                    if not success:
                        logger.warning(f"Failed to send welcome email for user: {user.username}")
                except Exception as e:
                    logger.warning(f"Welcome email failed for user {user.username}: {str(e)}")

            logger.info(f"User created successfully: {user.username} with roles: {roles or []}")
            return user, password, task_id

        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Integrity error creating user: {str(e)}")
            if 'username' in str(e):
                raise ValueError(f"Username '{username}' already exists")
            elif 'email' in str(e):
                raise ValueError(f"Email '{email}' already exists")
            else:
                raise ValueError("User creation failed due to data constraint")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating user: {str(e)}")
            raise

    @staticmethod
    def bulk_create_student_accounts(send_welcome_emails=True, created_by_user_id=None):
        """
        Create user accounts for all participants without accounts.
        Optimized for bulk operations.

        Args:
            send_welcome_emails: Whether to send welcome emails
            created_by_user_id: ID of user performing bulk creation

        Returns:
            dict: Results with created accounts and statistics
        """
        logger = logging.getLogger('user_service')

        try:
            # Optimized query: find participants without users using NOT EXISTS
            participants_without_users = (
                db.session.query(Participant)
                .filter(
                    ~exists().where(User.participant_id == Participant.id)
                )
                .options(selectinload(Participant.user))  # In case some exist
                .all()
            )

            if not participants_without_users:
                return {
                    'success': True,
                    'created_count': 0,
                    'failed_count': 0,
                    'created_accounts': [],
                    'failed_accounts': [],
                    'message': 'All participants already have user accounts'
                }

            # Get student role for bulk assignment
            student_role = (
                db.session.query(Role)
                .filter_by(name=RoleType.STUDENT)
                .first()
            )

            if not student_role:
                raise ValueError("Student role not found. Please initialize default roles.")

            created_accounts = []
            failed_accounts = []
            welcome_email_tasks = []

            # Process in batches to avoid memory issues
            batch_size = 50
            total_batches = (len(participants_without_users) + batch_size - 1) // batch_size

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(participants_without_users))
                batch_participants = participants_without_users[start_idx:end_idx]

                try:
                    # Process batch
                    for participant in batch_participants:
                        try:
                            # Create user account for participant
                            user, password = participant.create_user_account()

                            # Add student role
                            user.roles.append(student_role)

                            db.session.flush()  # Get user ID without committing

                            created_accounts.append({
                                'participant': participant,
                                'user': user,
                                'username': user.username,
                                'password': password,
                                'participant_id': participant.unique_id
                            })

                            # Queue welcome email if requested
                            if send_welcome_emails:
                                welcome_email_tasks.append((user.id, password))

                        except Exception as e:
                            logger.error(f"Failed to create account for participant {participant.unique_id}: {e}")
                            failed_accounts.append({
                                'participant': participant,
                                'error': str(e)
                            })
                            continue

                    # Commit batch
                    db.session.commit()
                    logger.info(
                        f"Processed batch {batch_num + 1}/{total_batches}: {len(batch_participants)} participants")

                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Batch {batch_num + 1} failed: {e}")
                    # Mark all participants in this batch as failed
                    for participant in batch_participants:
                        failed_accounts.append({
                            'participant': participant,
                            'error': f"Batch processing failed: {str(e)}"
                        })

            # Send welcome emails in background (don't block the response)
            email_task_ids = []
            if welcome_email_tasks:
                for user_id, password in welcome_email_tasks:
                    try:
                        success, task_id = AuthService.send_welcome_email(user_id, password)
                        if success and task_id:
                            email_task_ids.append(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to queue welcome email for user {user_id}: {e}")

            results = {
                'success': True,
                'created_count': len(created_accounts),
                'failed_count': len(failed_accounts),
                'created_accounts': created_accounts,
                'failed_accounts': failed_accounts,
                'email_task_ids': email_task_ids,
                'message': f'Created {len(created_accounts)} accounts, {len(failed_accounts)} failed'
            }

            logger.info(f"Bulk account creation completed: {results['message']}")
            return results

        except Exception as e:
            db.session.rollback()
            logger.error(f"Bulk account creation failed: {str(e)}")
            raise

    @staticmethod
    def manage_student_representative_role(user_id, action='promote', managed_by_user_id=None):
        """
        Promote or revoke student representative role.

        Args:
            user_id: User ID to modify
            action: 'promote' or 'revoke'
            managed_by_user_id: ID of user performing the action

        Returns:
            User: Updated user object
        """
        logger = logging.getLogger('user_service')

        try:
            # Optimized query: eager load participant and roles
            user = (
                db.session.query(User)
                .options(
                    joinedload(User.participant),
                    joinedload(User.roles)
                )
                .filter_by(id=user_id)
                .first()
            )

            if not user:
                raise ValueError("User not found")

            if not user.is_student():
                raise ValueError("User must be a student (have participant record)")

            # Get student representative role
            student_rep_role = (
                db.session.query(Role)
                .filter_by(name=RoleType.STUDENT_REPRESENTATIVE)
                .first()
            )

            if not student_rep_role:
                raise ValueError("Student representative role not found")

            has_role = student_rep_role in user.roles

            if action == 'promote':
                if has_role:
                    raise ValueError("User is already a student representative")

                user.roles.append(student_rep_role)
                action_msg = "promoted to"

            elif action == 'revoke':
                if not has_role:
                    raise ValueError("User is not a student representative")

                user.roles.remove(student_rep_role)
                action_msg = "revoked from"

            else:
                raise ValueError("Invalid action. Must be 'promote' or 'revoke'")

            db.session.commit()

            logger.info(f"User {user.username} {action_msg} student representative by {managed_by_user_id}")
            return user

        except Exception as e:
            db.session.rollback()
            logger.error(f"Role management error: {str(e)}")
            raise

    @staticmethod
    def get_users_by_role(role_name, include_inactive=False, limit=None, offset=0,
                          with_participant_data=False):
        """
        Get all users with a specific role using optimized queries.

        Args:
            role_name: Role name to filter by
            include_inactive: Include inactive users
            limit: Maximum number of results
            offset: Offset for pagination
            with_participant_data: Whether to eager load participant data

        Returns:
            list: List of User objects
        """
        try:
            # Base query with optimized joins
            query = (
                db.session.query(User)
                .join(User.roles)
                .filter(Role.name == role_name)
                .options(joinedload(User.roles))
            )

            # Add participant data if requested
            if with_participant_data:
                query = query.options(joinedload(User.participant))

            # Filter by active status
            if not include_inactive:
                query = query.filter(User.is_active == True)

            # Apply ordering using role hierarchy for consistent results
            query = query.join(Role, User.roles).order_by(
                Role.hierarchy_level.desc(),
                User.last_name,
                User.first_name
            )

            # Apply pagination
            if limit:
                query = query.limit(limit)
            if offset:
                query = query.offset(offset)

            return query.all()

        except Exception as e:
            logging.getLogger('user_service').error(f"Error getting users by role: {str(e)}")
            raise

    @staticmethod
    def get_student_users(include_inactive=False, classroom=None, limit=None, offset=0):
        """
        Get all student users (participants with accounts) using optimized queries.

        Args:
            include_inactive: Include inactive users
            classroom: Filter by classroom
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            list: List of User objects with participant data
        """
        try:
            # Optimized query: join with participant and eager load relationships
            query = (
                db.session.query(User)
                .join(User.participant)
                .options(
                    contains_eager(User.participant),
                    selectinload(User.roles)
                )
            )

            # Filter by active status
            if not include_inactive:
                query = query.filter(User.is_active == True)

            # Filter by classroom if specified
            if classroom:
                query = query.filter(Participant.classroom == classroom)

            # Order by participant ID for consistent results
            query = query.order_by(Participant.unique_id)

            # Apply pagination
            if limit:
                query = query.limit(limit)
            if offset:
                query = query.offset(offset)

            return query.all()

        except Exception as e:
            logging.getLogger('user_service').error(f"Error getting student users: {str(e)}")
            raise

    @staticmethod
    def get_users_without_participant_accounts():
        """
        Get participants who don't have user accounts yet.
        Useful for identifying who needs accounts created.

        Returns:
            list: List of Participant objects without user accounts
        """
        try:
            # Optimized query using NOT EXISTS
            participants = (
                db.session.query(Participant)
                .filter(
                    ~exists().where(User.participant_id == Participant.id)
                )
                .order_by(Participant.unique_id)
                .all()
            )

            return participants

        except Exception as e:
            logging.getLogger('user_service').error(f"Error getting participants without accounts: {str(e)}")
            raise

    @staticmethod
    def search_users(search_term, role_filter=None, status_filter=None, limit=20):
        """
        Search users by name, username, or email with optimized queries.

        Args:
            search_term: Search string
            role_filter: Filter by specific role
            status_filter: 'active', 'inactive', or None for all
            limit: Maximum results

        Returns:
            list: List of matching User objects
        """
        try:
            search_pattern = f"%{search_term}%"

            # Base query with eager loading
            query = (
                db.session.query(User)
                .options(
                    selectinload(User.roles),
                    joinedload(User.participant)
                )
            )

            # Apply search filters using indexed columns
            query = query.filter(
                or_(
                    User.first_name.ilike(search_pattern),
                    User.last_name.ilike(search_pattern),
                    User.username.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    # Also search participant unique_id if participant exists
                    and_(
                        User.participant_id.isnot(None),
                        exists().where(
                            and_(
                                Participant.id == User.participant_id,
                                Participant.unique_id.ilike(search_pattern)
                            )
                        )
                    )
                )
            )

            # Apply role filter
            if role_filter:
                query = (
                    query.join(User.roles)
                    .filter(Role.name == role_filter)
                )

            # Apply status filter
            if status_filter == 'active':
                query = query.filter(User.is_active == True)
            elif status_filter == 'inactive':
                query = query.filter(User.is_active == False)

            # Order by relevance (exact matches first, then partial)
            query = query.order_by(
                case(
                    (User.username.ilike(search_term), 1),
                    (User.email.ilike(search_term), 2),
                    (User.first_name.ilike(search_term), 3),
                    (User.last_name.ilike(search_term), 4),
                    else_=5
                ),
                User.last_name,
                User.first_name
            )

            return query.limit(limit).all()

        except Exception as e:
            logging.getLogger('user_service').error(f"Error searching users: {str(e)}")
            raise

    @staticmethod
    def get_user_statistics():
        """
        Get comprehensive user statistics using optimized queries.

        Returns:
            dict: Statistics about users in the system
        """
        try:
            # Use subqueries for efficient counting
            stats = {}

            # Total users
            stats['total_users'] = db.session.query(func.count(User.id)).scalar()

            # Active vs inactive
            active_count = (
                db.session.query(func.count(User.id))
                .filter(User.is_active == True)
                .scalar()
            )
            stats['active_users'] = active_count
            stats['inactive_users'] = stats['total_users'] - active_count

            # Users by role (optimized with single query)
            role_counts = (
                db.session.query(
                    Role.name,
                    Role.display_name,
                    func.count(User.id).label('count')
                )
                .join(User.roles)
                .filter(User.is_active == True)
                .group_by(Role.id, Role.name, Role.display_name)
                .order_by(Role.hierarchy_level.desc())
                .all()
            )

            stats['by_role'] = {
                role.name: {
                    'display_name': role.display_name,
                    'count': role.count
                }
                for role in role_counts
            }

            # Student-specific statistics
            student_stats = (
                db.session.query(
                    func.count(User.id).label('total_students'),
                    func.count(
                        case((Participant.classroom == current_app.config.get('LAPTOP_CLASSROOM'), 1))
                    ).label('laptop_classroom'),
                    func.count(
                        case((Participant.classroom == current_app.config.get('NO_LAPTOP_CLASSROOM'), 1))
                    ).label('no_laptop_classroom')
                )
                .join(User.participant)
                .filter(User.is_active == True)
                .first()
            )

            stats['students'] = {
                'total': student_stats.total_students or 0,
                'laptop_classroom': student_stats.laptop_classroom or 0,
                'no_laptop_classroom': student_stats.no_laptop_classroom or 0
            }

            # Recent registrations (last 30 days)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            stats['recent_registrations'] = (
                db.session.query(func.count(User.id))
                .filter(User.created_at >= thirty_days_ago)
                .scalar()
            )

            # Users without participant accounts (staff)
            stats['staff_users'] = (
                db.session.query(func.count(User.id))
                .filter(
                    and_(
                        User.participant_id.is_(None),
                        User.is_active == True
                    )
                )
                .scalar()
            )

            return stats

        except Exception as e:
            logging.getLogger('user_service').error(f"Error getting user statistics: {str(e)}")
            raise

    @staticmethod
    def get_users_needing_attention():
        """
        Get users that may need administrative attention.

        Returns:
            dict: Lists of users needing attention
        """
        try:
            # Users locked due to failed login attempts
            locked_users = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter(
                    and_(
                        User.locked_until.isnot(None),
                        User.locked_until > func.now()
                    )
                )
                .order_by(User.locked_until.desc())
                .all()
            )

            # Users with high failed login attempts (but not locked yet)
            high_failed_attempts = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter(
                    and_(
                        User.failed_login_attempts >= 3,
                        User.is_active == True,
                        or_(
                            User.locked_until.is_(None),
                            User.locked_until <= func.now()
                        )
                    )
                )
                .order_by(User.failed_login_attempts.desc())
                .all()
            )

            # Users who haven't logged in recently (if they have login history)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            inactive_users = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter(
                    and_(
                        User.is_active == True,
                        User.last_login.isnot(None),
                        User.last_login < thirty_days_ago
                    )
                )
                .order_by(User.last_login.asc())
                .limit(20)  # Top 20 most inactive
                .all()
            )

            # New users who haven't logged in yet
            never_logged_in = (
                db.session.query(User)
                .options(joinedload(User.participant))
                .filter(
                    and_(
                        User.is_active == True,
                        User.last_login.is_(None),
                        User.created_at < thirty_days_ago  # Created more than 30 days ago
                    )
                )
                .order_by(User.created_at.asc())
                .all()
            )

            return {
                'locked_users': locked_users,
                'high_failed_attempts': high_failed_attempts,
                'inactive_users': inactive_users,
                'never_logged_in': never_logged_in
            }

        except Exception as e:
            logging.getLogger('user_service').error(f"Error getting users needing attention: {str(e)}")
            raise

    @staticmethod
    def validate_role_assignment(user, target_roles, performed_by_user):
        """
        Validate if a user can be assigned specific roles.

        Args:
            user: User to assign roles to
            target_roles: List of role names to assign
            performed_by_user: User performing the assignment

        Returns:
            tuple: (valid: bool, message: str)
        """
        try:
            # Get target role objects
            target_role_objects = (
                db.session.query(Role)
                .filter(Role.name.in_(target_roles))
                .all()
            )

            if len(target_role_objects) != len(target_roles):
                found_roles = [r.name for r in target_role_objects]
                missing_roles = set(target_roles) - set(found_roles)
                return False, f"Invalid roles: {', '.join(missing_roles)}"

            # Check if performed_by_user has permission to assign these roles
            if not performed_by_user.has_permission(Permission.MANAGE_ROLES):
                return False, "Insufficient permissions to manage roles"

            # Check role hierarchy - can't assign roles higher than your own
            performer_highest_level = 0
            if performed_by_user.roles:
                performer_highest_level = max(role.hierarchy_level for role in performed_by_user.roles)

            for role in target_role_objects:
                if role.hierarchy_level >= performer_highest_level:
                    return False, f"Cannot assign role '{role.display_name}' - insufficient authority"

            # Validate role combinations
            role_names = [r.name for r in target_role_objects]

            # Students can't have admin roles
            if user.is_student() and any(role in [RoleType.ADMIN, RoleType.CHAPLAIN] for role in role_names):
                return False, "Students cannot be assigned administrative roles"

            # Admin roles shouldn't have student roles
            if any(role in [RoleType.ADMIN, RoleType.CHAPLAIN] for role in role_names):
                if RoleType.STUDENT in role_names or RoleType.STUDENT_REPRESENTATIVE in role_names:
                    return False, "Administrative roles cannot be combined with student roles"

            return True, "Role assignment is valid"

        except Exception as e:
            logging.getLogger('user_service').error(f"Role validation error: {str(e)}")
            return False, "Error validating role assignment"
