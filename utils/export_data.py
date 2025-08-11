def export_participants_to_excel():
    """
    Export participant data to Excel file with columns:
    - Name
    - Unique ID
    - Saturday Session Time Slot
    - Sunday Session Time Slot

    Returns:
        tuple: (excel_data, filename)
    """
    import pandas as pd
    from io import BytesIO
    from datetime import datetime
    from models import Participant, Session

    # Query all participants with their session information
    participants = Participant.query.all()

    # Prepare data for export
    data = []
    for participant in participants:
        # Get session time slots
        saturday_session = Session.query.get(participant.saturday_session_id)
        sunday_session = Session.query.get(participant.sunday_session_id)

        data.append({
            'Name': participant.name,
            # 'Unique ID': participant.unique_id,
            'Classroom': participant.classroom,
            'Phone': participant.phone,
            'Email': participant.email,
            'Saturday Session': saturday_session.time_slot if saturday_session else 'N/A',
            'Sunday Session': sunday_session.time_slot if sunday_session else 'N/A'
        })

    # Create DataFrame
    df = pd.DataFrame(data)

    # Create Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Participants', index=False)

        # Get the worksheet to adjust column widths
        worksheet = writer.sheets['Participants']

        # Set column widths to accommodate the content
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).apply(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'participants_export_{timestamp}.xlsx'

    # Seek to the beginning of the file
    output.seek(0)

    return output.getvalue(), filename
