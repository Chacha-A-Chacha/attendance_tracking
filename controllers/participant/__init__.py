from flask import Blueprint

participant_bp = Blueprint('participant', __name__)


from . import participant
