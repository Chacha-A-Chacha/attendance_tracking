import pandas as pd
from models.participant import Participant
from app import db

def import_spreadsheet(file_path):
    """Import participant data from spreadsheet"""
    df = pd.read_csv(file_path)
    
    # Clean column names
    df.columns = [col.strip() for col in df.columns]
    
    participants_added = 0
    
    for _, row in df.iterrows():
        # Check if participant already exists
        if Participant.query.filter_by(email=row['Email Address']).first():
            continue
            
        # Create new participant
        has_laptop = 'Yes' in row['Do you have a laptop?']
        classroom = '203' if has_laptop else '204'
        
        participant = Participant(
            unique_id=Participant.generate_unique_id(),
            email=row['Email Address'],
            name=row['Official Name'],
            phone=row['Phone number'],
            has_laptop=has_laptop,
            saturday_session=row['Saturday time session'],
            sunday_session=row['Sunday Time Session'],
            classroom=classroom
        )
        
        db.session.add(participant)
        participants_added += 1                                          
        
    db.session.commit()
    return participants_added
