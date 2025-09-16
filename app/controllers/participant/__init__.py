from flask import Blueprint

participant_portal_bp = Blueprint('participant_portal', __name__)

from . import participant
