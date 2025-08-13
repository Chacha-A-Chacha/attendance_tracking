# services/participant_service.py
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app.models import Participant, Session
from app.services.qrcode_generator import QRCodeGenerator
from app.utils.data_processing import clean_phone_number, clean_email, normalize_name
from app.utils.session_mapper import find_available_session
from app import db


def add_individual_participant(data):
    """
    Add an individual participant to the system

    Args:
        data: Dictionary containing participant information
             {
                'name': 'Participant Name',
                'email': 'email@example.com',
                'phone': '1234567890',
                'has_laptop': True/False,
                'saturday_session_id': 1,
                'sunday_session_id': 2
             }

    Returns:
        Dictionary with result information
    """
    try:
        # Clean and validate input data
        name = normalize_name(data.get('name', ''))
        email = clean_email(data.get('email', ''))
        phone = clean_phone_number(data.get('phone', ''))
        has_laptop = data.get('has_laptop', False)
        saturday_session_id = data.get('saturday_session_id')
        sunday_session_id = data.get('sunday_session_id')

        # Validate required fields
        if not name or not email or not phone:
            return {
                'success': False,
                'message': 'Name, email, and phone are required fields',
                'error_code': 'missing_required_fields'
            }

        # Check if participant already exists
        existing_participant = Participant.query.filter_by(email=email).first()
        if existing_participant:
            return {
                'success': False,
                'message': f'A participant with email {email} already exists',
                'error_code': 'duplicate_email'
            }

        # Determine classroom based on laptop availability
        classroom = current_app.config['LAPTOP_CLASSROOM'] if has_laptop else current_app.config['NO_LAPTOP_CLASSROOM']

        # Verify and handle session assignments
        # Check Saturday session
        if saturday_session_id:
            saturday_session = Session.query.get(saturday_session_id)
            if not saturday_session or saturday_session.day != 'Saturday':
                return {
                    'success': False,
                    'message': 'Invalid Saturday session',
                    'error_code': 'invalid_saturday_session'
                }

            # Check capacity and find available session if needed
            final_saturday_session = find_available_session('Saturday', has_laptop, saturday_session_id)
            if not final_saturday_session:
                return {
                    'success': False,
                    'message': 'No available Saturday sessions',
                    'error_code': 'no_available_saturday_session'
                }

            if final_saturday_session.id != saturday_session_id:
                # Session reassignment occurred due to capacity
                saturday_reassigned = True
                saturday_session_id = final_saturday_session.id
            else:
                saturday_reassigned = False
        else:
            return {
                'success': False,
                'message': 'Saturday session is required',
                'error_code': 'missing_saturday_session'
            }

        # Check Sunday session
        if sunday_session_id:
            sunday_session = Session.query.get(sunday_session_id)
            if not sunday_session or sunday_session.day != 'Sunday':
                return {
                    'success': False,
                    'message': 'Invalid Sunday session',
                    'error_code': 'invalid_sunday_session'
                }

            # Check capacity and find available session if needed
            final_sunday_session = find_available_session('Sunday', has_laptop, sunday_session_id)
            if not final_sunday_session:
                return {
                    'success': False,
                    'message': 'No available Sunday sessions',
                    'error_code': 'no_available_sunday_session'
                }

            if final_sunday_session.id != sunday_session_id:
                # Session reassignment occurred due to capacity
                sunday_reassigned = True
                sunday_session_id = final_sunday_session.id
            else:
                sunday_reassigned = False
        else:
            return {
                'success': False,
                'message': 'Sunday session is required',
                'error_code': 'missing_sunday_session'
            }

        # Create new participant with unique ID
        participant = Participant(
            unique_id=Participant.generate_unique_id(),
            name=name,
            email=email,
            phone=phone,
            has_laptop=has_laptop,
            saturday_session_id=saturday_session_id,
            sunday_session_id=sunday_session_id,
            classroom=classroom
        )

        db.session.add(participant)
        db.session.flush()  # Flush to get the ID

        # Generate QR code
        qr_generator = QRCodeGenerator()
        qr_path = qr_generator.generate_for_participant(participant)

        # Commit changes
        db.session.commit()

        # Prepare response
        response = {
            'success': True,
            'message': 'Participant added successfully',
            'participant': {
                'id': participant.id,
                'unique_id': participant.unique_id,
                'name': participant.name,
                'email': participant.email,
                'phone': participant.phone,
                'has_laptop': participant.has_laptop,
                'classroom': participant.classroom,
                'qr_code_path': qr_path
            },
            'reassignments': {}
        }

        # Add reassignment info if applicable
        if saturday_reassigned:
            response['reassignments']['saturday'] = {
                'original': saturday_session.time_slot,
                'assigned': final_saturday_session.time_slot
            }

        if sunday_reassigned:
            response['reassignments']['sunday'] = {
                'original': sunday_session.time_slot,
                'assigned': final_sunday_session.time_slot
            }

        return response

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error adding participant: {str(e)}")
        return {
            'success': False,
            'message': 'Database error occurred',
            'error_code': 'database_error'
        }
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error adding participant: {str(e)}")
        return {
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}',
            'error_code': 'unexpected_error'
        }
