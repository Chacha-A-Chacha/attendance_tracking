import re

def clean_phone_number(phone):
    """
    Standardize phone numbers to start with 254 (Kenya code)
    Examples:
        0113691613 -> 254113691613
        0714094335 -> 254714094335
        742462768 -> 254742462768
        +254105131277 -> 254105131277
    """
    if not phone:
        return ""
    
    # Convert to string if not already
    phone = str(phone).strip()
    
    # Remove any non-digit characters except leading +
    digits_only = re.sub(r'[^\d+]', '', phone)
    
    # Handle +254 prefix
    if digits_only.startswith('+254'):
        return digits_only.replace('+254', '254')
    
    # Handle numbers starting with 0
    if digits_only.startswith('0'):
        return '254' + digits_only[1:]
    
    # Handle numbers without any prefix
    if len(digits_only) <= 9:  # Assumes 9-digit local number without prefix
        return '254' + digits_only
    
    # Already in proper format or other case
    if digits_only.startswith('254'):
        return digits_only
    
    # Default case - just add 254 prefix if it seems like a valid number
    if len(digits_only) >= 9:
        return '254' + digits_only
    
    # Return original if we can't determine the format
    return phone

def clean_email(email):
    """
    Clean and normalize email addresses
    - Convert to lowercase
    - Remove leading/trailing whitespace
    """
    if not email:
        return ""
    
    return str(email).strip().lower()

def normalize_name(name):
    """
    Normalize name formatting
    - Remove extra spaces
    - Proper capitalization
    """
    if not name:
        return ""
    
    # Remove extra spaces
    name = re.sub(r'\s+', ' ', str(name).strip())
    
    # Title case (capitalize first letter of each word)
    name = name.title()
    
    return name

def clean_text_field(text):
    """
    General text field cleaning
    - Remove leading/trailing whitespace
    - Replace multiple spaces with single space
    """
    if not text:
        return ""
    
    return re.sub(r'\s+', ' ', str(text).strip())
