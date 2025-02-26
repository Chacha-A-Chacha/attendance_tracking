def clean_data(data):
    """Cleans the input data by removing any leading or trailing whitespace."""
    return [item.strip() for item in data if item.strip()]

def validate_email(email):
    """Validates the format of an email address."""
    import re
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

def process_attendance_data(raw_data):
    """Processes raw attendance data into a structured format."""
    cleaned_data = clean_data(raw_data)
    processed_data = []
    
    for entry in cleaned_data:
        parts = entry.split(',')
        if len(parts) == 3 and validate_email(parts[1]):
            processed_data.append({
                'name': parts[0],
                'email': parts[1],
                'session': parts[2]
            })
    
    return processed_data

def remove_duplicates(data):
    """Removes duplicate entries from the attendance data."""
    seen = set()
    unique_data = []
    for entry in data:
        identifier = (entry['name'], entry['email'])
        if identifier not in seen:
            seen.add(identifier)
            unique_data.append(entry)
    return unique_data