import os
import qrcode
from PIL import Image, ImageDraw, ImageFont
from flask import current_app
from app import db
from models.participant import Participant


class QRCodeGenerator:
    def __init__(self, base_path=None):
        """Initialize the QR code generator with optional custom path"""
        self.base_path = base_path

    def get_qrcode_path(self):
        """Get the QR code storage path from config or use provided path"""
        if self.base_path:
            return self.base_path
        return current_app.config['QR_CODE_FOLDER']

    def generate_for_participant(self, participant):
        """Generate QR code for a specific participant"""
        # Ensure participant is valid
        if not isinstance(participant, Participant) or not participant.unique_id:
            raise ValueError("Invalid participant or missing unique ID")

        # Generate the QR code
        qr_path = self._generate_qrcode(
            data=participant.unique_id,
            filename=f"{participant.unique_id}.png",
            participant_info=participant
        )

        # Update participant record with QR code path
        participant.qrcode_path = qr_path
        db.session.commit()

        return qr_path

    def generate_batch(self, participants):
        """Generate QR codes for multiple participants"""
        results = {
            'success': [],
            'errors': []
        }

        for participant in participants:
            try:
                qr_path = self.generate_for_participant(participant)
                results['success'].append({
                    'participant_id': participant.id,
                    'qr_path': qr_path
                })
            except Exception as e:
                results['errors'].append({
                    'participant_id': participant.id,
                    'error': str(e)
                })

        return results

    def _generate_qrcode(self, data, filename, participant_info=None):
        """Internal method to generate and save QR code"""
        # Create QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )

        # Add data
        qr.add_data(data)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # If participant info is provided, add name and session info to the QR code
        if participant_info:
            # Convert to RGB for adding text
            img = img.convert("RGB")

            # Create a larger canvas to include text
            qr_size = img.size[0]
            canvas_width = qr_size
            canvas_height = qr_size + 120  # Extra space for text

            canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
            canvas.paste(img, (0, 0))

            # Add text
            draw = ImageDraw.Draw(canvas)

            try:
                # Try to use a nice font, fallback to default if not available
                font = ImageFont.truetype("Arial", 16)
            except IOError:
                font = ImageFont.load_default()

            # Add participant info
            draw.text((10, qr_size + 10), f"Name: {participant_info.name}", fill="black", font=font)
            draw.text((10, qr_size + 40), f"ID: {participant_info.unique_id}", fill="black", font=font)
            draw.text((10, qr_size + 70), f"Class: {participant_info.classroom}", fill="black", font=font)

            img = canvas

        # Ensure directory exists
        qrcode_folder = self.get_qrcode_path()
        os.makedirs(qrcode_folder, exist_ok=True)

        # Save the image
        filepath = os.path.join(qrcode_folder, filename)
        img.save(filepath)

        return filepath

    def regenerate_qrcode(self, participant_id):
        """Regenerate QR code for a participant by ID"""
        participant = Participant.query.get(participant_id)
        if not participant:
            raise ValueError(f"Participant with ID {participant_id} not found")

        # Delete existing QR code if it exists
        if participant.qrcode_path and os.path.exists(participant.qrcode_path):
            try:
                os.remove(participant.qrcode_path)
            except OSError:
                pass  # Ignore errors when removing old file

        # Generate new QR code
        return self.generate_for_participant(participant)
