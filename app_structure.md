attendance_tracking/
│
├── app.py                    # Main application entry point
├── config.py                 # Configuration settings
├── requirements.txt          # Project dependencies
│   ├── package.json          # Project metadata and dependencies
│   ├── package-lock.json     # Lock file for npm dependencies
│
├── static/                   # Static files
│   ├── css/
│   │   ├── input.css         # Input styles
│   │   └── output.css        # Output styles
│   ├── js/
│   │   ├── qrcode-scanner.js # QR scanning logic
│   │   └── dashboard.js      # Admin dashboard functionality
│   └── images/
│
├── templates/                # HTML templates
│   ├── base.html             # Base template
│   ├── admin/
│   │   ├── dashboard.html    # Admin dashboard
│   │   ├── import.html       # Spreadsheet import page
│   │   ├── participant_details.html # Participant details page
│   │   ├── reports.html      # Attendance reports
│   │   └── session_attendance.html # Session attendance page
│   ├── check_in/
│   │   ├── scanner.html      # QR scanner interface
│   │   └── result.html       # Verification result
│   ├── emails/
│   │   ├── qrcode.html       # Email template for QR code
│   │   └── qrcode.txt        # Text version of the QR code email
│   └── participant/
│       ├── base.html         # Base template for participant pages
│       ├── dashboard.html     # Participant dashboard
│       ├── info.html         # Participant information page
│       └── landing.html      # Participant landing page
│
├── models/                   # Database models
│   ├── __init__.py
│   ├── attendance.py         # Attendance model
│   ├── participant.py        # Participant model
│   └── session.py            # Session model
│
├── controllers/              # Route handlers
│   ├── __init__.py
│   ├── admin.py              # Admin dashboard routes
│   ├── check_in.py           # Check-in process routes
│   ├── participant.py        # Participant info routes
│   └── api.py                # API routes
│
├── services/                 # Business logic
│   ├── __init__.py
│   ├── importer.py           # Spreadsheet import logic
│   ├── participant_service.py # Participant-related business logic
│   ├── qrcode_generator.py   # QR code generation
│   ├── verification.py       # Attendance verification
│   └── email_service.py      # Email service located in utils directory
│
└── utils/                    # Utility functions
    ├── __init__.py
    ├── data_processing.py    # Data cleaning functions
    └── session_mapper.py     # Maps sessions to classes
