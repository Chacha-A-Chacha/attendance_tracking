import pandas as pd
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app import db
from models import Participant, Session
from services.qrcode_generator import QRCodeGenerator

def init_sessions():
    """Initialize session data from config"""
    # Check if sessions already exist
    if Session.query.count() > 0:
        return
    
    # Create Saturday sessions
    saturday_sessions = current_app.config['SATURDAY_SESSIONS']
    for time_slot in saturday_sessions:
        session = Session(time_slot=time_slot, day='Saturday')
        db.session.add(session)
    
    # Create Sunday sessions
    sunday_sessions = current_app.config['SUNDAY_SESSIONS']
    for time_slot in sunday_sessions:
        session = Session(time_slot=time_slot, day='Sunday')
        db.session.add(session)
    
    db.session.commit()

def import_spreadsheet(file_path):
    """Import participant data from spreadsheet"""
    # Make sure sessions are initialized
    init_sessions()
    
    # Initialize QR code generator
    qr_generator = QRCodeGenerator()
    
    df = pd.read_csv(file_path)
    
    # Clean column names and handle potential encoding issues
    df.columns = [col.strip() for col in df.columns]
    
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
    
    try:
        for _, row in df.iterrows():
            # Check if participant already exists
            email = row[column_mapping['Email']]
            if Participant.query.filter_by(email=email).first():
                continue
            
            # Find the corresponding session objects
            saturday_time = row[column_mapping['Saturday']]
            sunday_time = row[column_mapping['Sunday']]
            
            saturday_session = Session.query.filter_by(
                day='Saturday', 
                time_slot=saturday_time
            ).first()
            
            sunday_session = Session.query.filter_by(
                day='Sunday', 
                time_slot=sunday_time
            ).first()
            
            if not saturday_session or not sunday_session:
                errors.append(f"Invalid session for {row[column_mapping['Name']]}")
                continue
            
            # Determine laptop status and classroom
            laptop_value = row[column_mapping['Laptop']]
            has_laptop = isinstance(laptop_value, str) and 'Yes' in laptop_value
            classroom = current_app.config['LAPTOP_CLASSROOM'] if has_laptop else current_app.config['NO_LAPTOP_CLASSROOM']
            
            # Create new participant
            participant = Participant(
                unique_id=Participant.generate_unique_id(),
                email=email,
                name=row[column_mapping['Name']],
                phone=row[column_mapping['Phone']],
                has_laptop=has_laptop,
                saturday_session_id=saturday_session.id,
                sunday_session_id=sunday_session.id,
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
            'errors': errors
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
    