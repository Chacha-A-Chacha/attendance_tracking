# forms/__init__.py
"""
Forms package for the enrollment system.

This package contains all Flask-WTF form classes used throughout the application.
All forms include proper validation, CSRF protection, and error handling.
"""

from .enrollment import (
    # Core enrollment forms
    EnrollmentForm,
    EditEnrollmentForm,
    ReceiptUpdateForm,
    SearchApplicationForm,
    EmailVerificationForm,

    # Base form class
    BaseEnrollmentForm,

    # Form choices constants
    ENROLLMENT_STATUS_CHOICES,
    PAYMENT_STATUS_CHOICES,
    HOW_DID_YOU_HEAR_CHOICES
)

# Make all forms available when importing from forms package
__all__ = [
    # Form classes
    'EnrollmentForm',
    'EditEnrollmentForm',
    'ReceiptUpdateForm',
    'SearchApplicationForm',
    'EmailVerificationForm',
    'BaseEnrollmentForm',

    # Constants
    'ENROLLMENT_STATUS_CHOICES',
    'PAYMENT_STATUS_CHOICES',
    'HOW_DID_YOU_HEAR_CHOICES'
]
