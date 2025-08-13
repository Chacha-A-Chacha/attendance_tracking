from flask import Blueprint

enrollment_bp = Blueprint('enrollment', __name__)

from . import enrollment
