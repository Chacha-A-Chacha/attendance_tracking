attendance_tracking/
│
├── app.py                    # Main application entry point
├── config.py                 # Configuration settings
├── requirements.txt          # Project dependencies
│
├── static/                   # Static files
│   ├── css/
│   │   └── styles.css
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
│   │   └── reports.html      # Attendance reports
│   ├── check_in/
│   │   ├── scanner.html      # QR scanner interface
│   │   └── result.html       # Verification result
│   └── participant/
│       └── info.html         # Participant information page
│
├── models/                   # Database models
│   ├── __init__.py
│   ├── participant.py        # Participant model
│   ├── session.py            # Session model
│   └── attendance.py         # Attendance model
│
├── controllers/              # Route handlers
│   ├── __init__.py
│   ├── admin.py              # Admin dashboard routes
│   ├── check_in.py           # Check-in process routes
│   └── participant.py        # Participant info routes
│
├── services/                 # Business logic
│   ├── __init__.py
│   ├── importer.py           # Spreadsheet import logic
│   ├── qrcode_generator.py   # QR code generation
│   └── verification.py       # Attendance verification
│
└── utils/                    # Utility functions
    ├── __init__.py
    ├── data_processing.py    # Data cleaning functions
    └── session_mapper.py     # Maps sessions to classes