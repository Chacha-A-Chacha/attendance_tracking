from flask import Blueprint, render_template, request, jsonify
from models import Participant

participant_bp = Blueprint('participant', __name__)


@participant_bp.route('/participant/<int:participant_id>', methods=['GET'])
def get_participant_info(participant_id):
    participant = Participant.query.get(participant_id)
    if participant:
        return render_template('participant/info.html', participant=participant)
    return jsonify({'error': 'Participant not found'}), 404


@participant_bp.route('/participant', methods=['POST'])
def create_participant():
    data = request.json
    new_participant = Participant(name=data['name'], email=data['email'])
    new_participant.save()
    return jsonify({'message': 'Participant created successfully'}), 201


@participant_bp.route('/participant/<int:participant_id>', methods=['PUT'])
def update_participant(participant_id):
    participant = Participant.query.get(participant_id)
    if not participant:
        return jsonify({'error': 'Participant not found'}), 404

    data = request.json
    participant.name = data.get('name', participant.name)
    participant.email = data.get('email', participant.email)
    participant.save()
    return jsonify({'message': 'Participant updated successfully'}), 200


@participant_bp.route('/participant/<int:participant_id>', methods=['DELETE'])
def delete_participant(participant_id):
    participant = Participant.query.get(participant_id)
    if not participant:
        return jsonify({'error': 'Participant not found'}), 404

    participant.delete()
    return jsonify({'message': 'Participant deleted successfully'}), 200
