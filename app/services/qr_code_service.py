# services/qr_code_service.py
"""
QR Code generation service for participant check-in codes.
Generates QR codes with JSON data format containing unique_id and UUID.
Stores codes in static folder for nginx serving with secure access.
"""

import os
import json
import secrets
import qrcode
import logging
from flask import current_app, url_for
from sqlalchemy.exc import SQLAlchemyError

from app.models.participant import Participant
from app.extensions import db


class QRCodeError:
    """QR Code service error codes."""
    PARTICIPANT_NOT_FOUND = 'participant_not_found'
    INVALID_PARTICIPANT = 'invalid_participant'
    GENERATION_FAILED = 'generation_failed'
    FILE_SAVE_ERROR = 'file_save_error'
    PERMISSION_DENIED = 'permission_denied'
    MISSING_CONFIG = 'missing_config'


class QRCodeService:
    """Service for generating and managing participant QR codes."""

    @staticmethod
    def generate_for_participant(participant_id=None, unique_id=None, user_id=None):
        """
        Generate QR code for a specific participant.

        Args:
            participant_id: Participant ID (UUID)
            unique_id: Participant unique_id (5-digit)
            user_id: User ID for permission validation (optional)

        Returns:
            dict: Generation result with QR code URL and metadata
        """
        logger = logging.getLogger('qr_code_service')

        try:
            # Get participant by ID or unique_id
            participant = None
            if participant_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(id=participant_id)
                    .first()
                )
            elif unique_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(unique_id=unique_id)
                    .first()
                )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': QRCodeError.PARTICIPANT_NOT_FOUND
                }

            # Validate participant has required data
            if not participant.unique_id or not participant.id:
                return {
                    'success': False,
                    'message': 'Participant missing required identifiers',
                    'error_code': QRCodeError.INVALID_PARTICIPANT
                }

            # Permission check if user_id provided
            if user_id and participant.user_id != user_id:
                return {
                    'success': False,
                    'message': 'Permission denied to generate QR code',
                    'error_code': QRCodeError.PERMISSION_DENIED
                }

            # Check if QR code already exists and is valid
            if participant.qrcode_path:
                qr_url = QRCodeService._get_static_url(participant.qrcode_path)
                if QRCodeService._validate_existing_qr(participant.qrcode_path):
                    logger.info(f"Using existing QR code for participant {participant.unique_id}")
                    return {
                        'success': True,
                        'message': 'QR code already exists',
                        'qr_url': qr_url,
                        'qr_path': participant.qrcode_path,
                        'participant': {
                            'id': participant.id,
                            'unique_id': participant.unique_id,
                            'full_name': participant.full_name
                        },
                        'generated': False  # Existing QR code
                    }

            # Generate new QR code
            qr_data = {
                'unique_id': participant.unique_id,
                'id': str(participant.id)
            }

            # Create secure filename
            secure_token = secrets.token_urlsafe(12)
            filename = f"{participant.id}_{secure_token}.png"

            # Generate QR code file
            qr_path = QRCodeService._generate_qr_file(qr_data, filename)

            if not qr_path:
                return {
                    'success': False,
                    'message': 'Failed to generate QR code file',
                    'error_code': QRCodeError.GENERATION_FAILED
                }

            # Update participant record with QR path
            participant.qrcode_path = qr_path
            db.session.commit()

            # Get static URL for template display
            qr_url = QRCodeService._get_static_url(qr_path)

            logger.info(f"Generated QR code for participant {participant.unique_id}: {filename}")

            return {
                'success': True,
                'message': 'QR code generated successfully',
                'qr_url': qr_url,
                'qr_path': qr_path,
                'participant': {
                    'id': participant.id,
                    'unique_id': participant.unique_id,
                    'full_name': participant.full_name
                },
                'generated': True  # Newly generated
            }

        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error generating QR code: {str(e)}")
            return {
                'success': False,
                'message': 'Database error during QR generation',
                'error_code': QRCodeError.GENERATION_FAILED
            }
        except Exception as e:
            logger.error(f"Unexpected error generating QR code: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Unexpected error during QR generation',
                'error_code': QRCodeError.GENERATION_FAILED
            }

    @staticmethod
    def get_participant_qr_info(participant_id=None, unique_id=None, user_id=None):
        """
        Get QR code information for a participant without generating new code.

        Args:
            participant_id: Participant ID (UUID)
            unique_id: Participant unique_id (5-digit)
            user_id: User ID for permission validation (optional)

        Returns:
            dict: QR code information and availability status
        """
        logger = logging.getLogger('qr_code_service')

        try:
            # Get participant
            participant = None
            if participant_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(id=participant_id)
                    .first()
                )
            elif unique_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(unique_id=unique_id)
                    .first()
                )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': QRCodeError.PARTICIPANT_NOT_FOUND
                }

            # Permission check if user_id provided
            if user_id and participant.user_id != user_id:
                return {
                    'success': False,
                    'message': 'Permission denied to access QR code info',
                    'error_code': QRCodeError.PERMISSION_DENIED
                }

            # Check QR code status
            has_qr_code = bool(participant.qrcode_path)
            qr_exists = False
            qr_url = None

            if has_qr_code:
                qr_exists = QRCodeService._validate_existing_qr(participant.qrcode_path)
                if qr_exists:
                    qr_url = QRCodeService._get_static_url(participant.qrcode_path)

            return {
                'success': True,
                'participant': {
                    'id': participant.id,
                    'unique_id': participant.unique_id,
                    'full_name': participant.full_name
                },
                'qr_code': {
                    'exists': qr_exists,
                    'has_path': has_qr_code,
                    'url': qr_url,
                    'path': participant.qrcode_path if qr_exists else None
                },
                'can_generate': not qr_exists  # Can generate if doesn't exist
            }

        except Exception as e:
            logger.error(f"Error getting QR info: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Error retrieving QR code information',
                'error_code': QRCodeError.GENERATION_FAILED
            }

    @staticmethod
    def regenerate_for_participant(participant_id=None, unique_id=None, user_id=None):
        """
        Regenerate QR code for a participant (replaces existing).

        Args:
            participant_id: Participant ID (UUID)
            unique_id: Participant unique_id (5-digit)
            user_id: User ID for permission validation (optional)

        Returns:
            dict: Regeneration result with new QR code URL
        """
        logger = logging.getLogger('qr_code_service')

        try:
            # Get participant
            participant = None
            if participant_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(id=participant_id)
                    .first()
                )
            elif unique_id:
                participant = (
                    db.session.query(Participant)
                    .filter_by(unique_id=unique_id)
                    .first()
                )

            if not participant:
                return {
                    'success': False,
                    'message': 'Participant not found',
                    'error_code': QRCodeError.PARTICIPANT_NOT_FOUND
                }

            # Permission check if user_id provided
            if user_id and participant.user_id != user_id:
                return {
                    'success': False,
                    'message': 'Permission denied to regenerate QR code',
                    'error_code': QRCodeError.PERMISSION_DENIED
                }

            # Delete existing QR code file if it exists
            if participant.qrcode_path:
                QRCodeService._cleanup_qr_file(participant.qrcode_path)

            # Clear the QR path from database
            participant.qrcode_path = None
            db.session.commit()

            # Generate new QR code
            result = QRCodeService.generate_for_participant(
                participant_id=participant.id,
                user_id=user_id
            )

            if result['success']:
                result['message'] = 'QR code regenerated successfully'
                result['regenerated'] = True
                logger.info(f"Regenerated QR code for participant {participant.unique_id}")

            return result

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error regenerating QR code: {str(e)}", exc_info=True)
            return {
                'success': False,
                'message': 'Error regenerating QR code',
                'error_code': QRCodeError.GENERATION_FAILED
            }

    @staticmethod
    def validate_qr_data(qr_content):
        """
        Validate QR code content format.

        Args:
            qr_content: String content from QR code scan

        Returns:
            dict: Validation result with parsed data
        """
        try:
            # Try to parse as JSON first
            try:
                qr_data = json.loads(qr_content)
                if isinstance(qr_data, dict) and 'unique_id' in qr_data:
                    return {
                        'success': True,
                        'format': 'json',
                        'data': qr_data,
                        'unique_id': qr_data.get('unique_id'),
                        'participant_id': qr_data.get('id')
                    }
            except json.JSONDecodeError:
                pass

            # Try as plain unique_id (legacy support)
            if qr_content.isdigit() and len(qr_content) == 5:
                return {
                    'success': True,
                    'format': 'plain',
                    'data': qr_content,
                    'unique_id': qr_content,
                    'participant_id': None
                }

            return {
                'success': False,
                'message': 'Invalid QR code format',
                'format': 'unknown'
            }

        except Exception as e:
            logging.getLogger('qr_code_service').error(f"Error validating QR data: {str(e)}")
            return {
                'success': False,
                'message': 'Error validating QR code data',
                'format': 'error'
            }

    # Private Helper Methods

    @staticmethod
    def _generate_qr_file(qr_data, filename):
        """
        Generate QR code file with JSON data.

        Args:
            qr_data: Dictionary to encode in QR code
            filename: Target filename for QR code

        Returns:
            str: File path if successful, None if failed
        """
        try:
            # Get QR code folder from config
            qr_folder = current_app.config.get('QR_CODE_FOLDER')
            if not qr_folder:
                logging.getLogger('qr_code_service').error("QR_CODE_FOLDER not configured")
                return None

            # Ensure directory exists
            os.makedirs(qr_folder, exist_ok=True)

            # Create QR code instance with high error correction
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )

            # Add JSON data to QR code
            json_data = json.dumps(qr_data, separators=(',', ':'))  # Compact JSON
            qr.add_data(json_data)
            qr.make(fit=True)

            # Create QR code image
            qr_image = qr.make_image(fill_color="black", back_color="white")

            # Save to file
            file_path = os.path.join(qr_folder, filename)
            qr_image.save(file_path, format='PNG')

            return file_path

        except Exception as e:
            logging.getLogger('qr_code_service').error(f"Error generating QR file: {str(e)}")
            return None

    @staticmethod
    def _get_static_url(qr_path):
        """
        Convert QR file path to static URL for template display.

        Args:
            qr_path: File system path to QR code

        Returns:
            str: Static URL for the QR code
        """
        try:
            if not qr_path:
                return None

            # Extract filename from path
            filename = os.path.basename(qr_path)

            # Build static URL
            # Assuming QR codes are in /static/qrcodes/
            return url_for('static', filename=f'qrcodes/{filename}')

        except Exception as e:
            logging.getLogger('qr_code_service').error(f"Error building static URL: {str(e)}")
            return None

    @staticmethod
    def _validate_existing_qr(qr_path):
        """
        Check if QR code file exists and is readable.

        Args:
            qr_path: File system path to QR code

        Returns:
            bool: True if QR code exists and is valid
        """
        try:
            return qr_path and os.path.isfile(qr_path) and os.access(qr_path, os.R_OK)
        except Exception:
            return False

    @staticmethod
    def _cleanup_qr_file(qr_path):
        """
        Safely delete QR code file.

        Args:
            qr_path: File system path to QR code
        """
        try:
            if qr_path and os.path.isfile(qr_path):
                os.remove(qr_path)
                logging.getLogger('qr_code_service').info(f"Cleaned up QR file: {qr_path}")
        except Exception as e:
            logging.getLogger('qr_code_service').warning(f"Could not delete QR file {qr_path}: {str(e)}")
            