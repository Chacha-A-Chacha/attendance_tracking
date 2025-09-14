# Updated services/importer.py

import pandas as pd
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from app.models import Participant, Session
from app.services.qrcode_generator import QRCodeGenerator
from app.services.session_classroom_service import SessionClassroomService
from app.utils.data_processing import clean_phone_number, clean_email, normalize_name, clean_text_field
from app.utils.session_mapper import normalize_session_time, get_session_by_time, find_available_session, get_default_session


def init_sessions():
    """
    Initialize session data from config.

    DEPRECATED: Use SessionClassroomService.init_sessions_from_config() instead.
    This wrapper is maintained for backward compatibility.
    """
    import warnings
    warnings.warn(
        "init_sessions() is deprecated. Use SessionClassroomService.init_sessions_from_config() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    # Delegate to the proper service method
    result = SessionClassroomService.init_sessions_from_config()
    return result


def import_spreadsheet(file_path):
    """Import participant data from spreadsheet"""
    # Make sure sessions are initialized
    init_sessions()

    # Initialize QR code generator
    qr_generator = QRCodeGenerator()

    # Handle different file types and encodings
    try:
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            import pandas as pd
            df = pd.read_excel(file_path)
        else:
            # Try different encodings for CSV
            try:
                df = pd.read_csv(file_path)
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(file_path, encoding='utf-8-sig')
                except UnicodeDecodeError:
                    try:
                        df = pd.read_csv(file_path, encoding='latin-1')
                    except Exception as e:
                        return {
                            'success': False,
                            'error': f"Unable to read file with multiple encodings: {str(e)}",
                            'participants_added': 0
                        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Error reading file: {str(e)}",
            'participants_added': 0
        }

    # Clean column names
    df.columns = [clean_text_field(col) for col in df.columns]

    # Map column names to more manageable names using partial matching
    column_mapping = {
        'Email': next((col for col in df.columns if 'Email' in col), None),
        'Name': next((col for col in df.columns if 'Name' in col), None),
        'Phone': next((col for col in df.columns if 'Phone' in col), None),
        'Saturday': next((col for col in df.columns if 'Saturday' in col), None),
        'Sunday': next((col for col in df.columns if 'Sunday' in col), None),
        'Laptop': next((col for col in df.columns if 'laptop' in col.lower()), None)
    }

    # Validate all required columns exist
    missing_columns = [key for key, value in column_mapping.items() if value is None]
    if missing_columns:
        return {
            'success': False,
            'error': f"Missing required columns: {', '.join(missing_columns)}",
            'participants_added': 0
        }

    participants_added = 0
    errors = []
    reassignments = []

    try:
        for _, row in df.iterrows():
            # Clean the input data
            email = clean_email(row[column_mapping['Email']])
            name = normalize_name(row[column_mapping['Name']])
            phone = clean_phone_number(row[column_mapping['Phone']])

            # Check if participant already exists
            if Participant.query.filter_by(email=email).first():
                continue

            # Normalize session times and handle missing values
            saturday_time = normalize_session_time(row[column_mapping['Saturday']])
            sunday_time = normalize_session_time(row[column_mapping['Sunday']])

            # Find the corresponding session objects
            saturday_session = None
            sunday_session = None

            # Check if Saturday session is valid
            if pd.isna(saturday_time) and saturday_time:
                saturday_session = get_session_by_time(saturday_time, 'Saturday')
            else:
                # No Saturday session selected, get default
                saturday_session = get_default_session('Saturday')
                if saturday_session:
                    saturday_time = saturday_session.time_slot
                    reassignments.append(f"{name}: Assigned default Saturday session {saturday_session.time_slot}")

            # Check if Sunday session is valid
            if pd.isna(sunday_time) and sunday_time:
                sunday_session = get_session_by_time(sunday_time, 'Sunday')
            else:
                # No Sunday session selected, get default
                sunday_session = get_default_session('Sunday')
                if sunday_session:
                    sunday_time = sunday_session.time_slot
                    reassignments.append(f"{name}: Assigned default Sunday session {sunday_session.time_slot}")

            # If either session is still missing, we can't proceed
            if not saturday_session or not sunday_session:
                errors.append(f"Unable to assign valid sessions for {name}: Saturday={saturday_time}, Sunday={sunday_time}")
                continue

            # Determine laptop status and classroom
            laptop_value = row[column_mapping['Laptop']]
            has_laptop = isinstance(laptop_value, str) and 'Yes' in laptop_value
            classroom = current_app.config['LAPTOP_CLASSROOM'] if has_laptop else current_app.config['NO_LAPTOP_CLASSROOM']

            # Check capacity and find available sessions if needed
            final_saturday_session = find_available_session('Saturday', has_laptop, saturday_session.id)
            final_sunday_session = find_available_session('Sunday', has_laptop, sunday_session.id)

            if not final_saturday_session:
                errors.append(f"No available Saturday sessions for {name}")
                continue
                
            if not final_sunday_session:
                errors.append(f"No available Sunday sessions for {name}")
                continue
            # Track if we had to reassign
            if saturday_session.id != final_saturday_session.id:
                reassignments.append(
                    f"{name}: Saturday session changed from {saturday_session.time_slot} to {final_saturday_session.time_slot}")

            if sunday_session.id != final_sunday_session.id:
                reassignments.append(
                    f"{name}: Sunday session changed from {sunday_session.time_slot} to {final_sunday_session.time_slot}")

            # Create new participant
            participant = Participant(
                unique_id=Participant.generate_unique_id(),
                email=email,
                name=name,
                phone=phone,
                has_laptop=has_laptop,
                saturday_session_id=final_saturday_session.id,
                sunday_session_id=final_sunday_session.id,
                classroom=classroom
            )

            db.session.add(participant)
            db.session.flush()  # Flush to get the ID

            # Generate QR code
            try:
                qr_generator.generate_for_participant(participant)
                participants_added += 1
            except Exception as e:
                errors.append(f"QR code generation failed for {participant.name}: {str(e)}")

        db.session.commit()

        return {
            'success': True,
            'participants_added': participants_added,
            'errors': errors,
            'reassignments': reassignments
        }

    except SQLAlchemyError as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e),
            'participants_added': 0
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': f"Unexpected error: {str(e)}",
            'participants_added': 0
        }
