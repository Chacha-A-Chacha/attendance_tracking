from qrcode import QRCode, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
import io
from PIL import Image

def generate_qr_code(data, version=1, error_correction=ERROR_CORRECT_L, box_size=10, border=4):
    """
    Generate a QR code image from the given data.

    :param data: The data to encode in the QR code.
    :param version: Version of the QR code (1 to 40).
    :param error_correction: Error correction level.
    :param box_size: Size of each box in the QR code grid.
    :param border: Thickness of the border (minimum is 4).
    :return: A PIL Image object of the generated QR code.
    """
    qr = QRCode(
        version=version,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    return img

def save_qr_code_image(data, file_path):
    """
    Generate and save a QR code image to the specified file path.

    :param data: The data to encode in the QR code.
    :param file_path: The file path where the QR code image will be saved.
    """
    img = generate_qr_code(data)
    img.save(file_path)