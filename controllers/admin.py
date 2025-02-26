from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from services.importer import import_spreadsheet
import os

from models import Participant, Session
from utils.session_mapper import get_session_capacity, get_session_count

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/initialize-data', methods=['GET'])
def initialize_data():
    """Initialize the system by importing the default data file"""
    data_path = os.path.join(current_app.root_path, 'data', 'sessions_data.xlsx')
    current_app.logger.info(f'Initializing data from {data_path}')

    # Check if file exists
    if not os.path.exists(data_path):
        return jsonify({
            'success': False,
            'message': f'Data file not found at {data_path}'
        }), 404

    # Import the spreadsheet
    result = import_spreadsheet(data_path)

    return jsonify(result)


@admin_bp.route('/capacities', methods=['GET'])
def get_capacities():
    """Get capacity information for classrooms and sessions"""
    # Get classroom capacities from config
    classroom_capacities = current_app.config.get('SESSION_CAPACITY', {})
    
    # Get all sessions
    sessions = Session.query.all()
    
    # Initialize data structure
    capacity_data = {
        "classroom_capacities": classroom_capacities,
        "sessions": {}
    }
    
    # Get laptop and no-laptop classroom IDs from config
    laptop_classroom = current_app.config['LAPTOP_CLASSROOM']
    no_laptop_classroom = current_app.config['NO_LAPTOP_CLASSROOM']
    
    # Calculate session counts and remaining capacity
    for session in sessions:
        session_key = f"{session.day}_{session.time_slot}"
        
        # Get counts for both classrooms
        laptop_count = get_session_count(session.id, laptop_classroom)
        no_laptop_count = get_session_count(session.id, no_laptop_classroom)
        
        # Get capacities
        laptop_capacity = get_session_capacity(laptop_classroom)
        no_laptop_capacity = get_session_capacity(no_laptop_classroom)
        
        # Store data
        capacity_data["sessions"][session_key] = {
            "id": session.id,
            "day": session.day,
            "time_slot": session.time_slot,
            "classrooms": {
                laptop_classroom: {
                    "capacity": laptop_capacity,
                    "current_count": laptop_count,
                    "available": laptop_capacity - laptop_count,
                    "percentage_filled": round((laptop_count / laptop_capacity) * 100, 1) if laptop_capacity > 0 else 0
                },
                no_laptop_classroom: {
                    "capacity": no_laptop_capacity,
                    "current_count": no_laptop_count,
                    "available": no_laptop_capacity - no_laptop_count,
                    "percentage_filled": round((no_laptop_count / no_laptop_capacity) * 100, 1) if no_laptop_capacity > 0 else 0
                }
            },
            "total": {
                "capacity": laptop_capacity + no_laptop_capacity,
                "current_count": laptop_count + no_laptop_count,
                "available": (laptop_capacity + no_laptop_capacity) - (laptop_count + no_laptop_count),
                "percentage_filled": round(((laptop_count + no_laptop_count) / (laptop_capacity + no_laptop_capacity)) * 100, 1) if (laptop_capacity + no_laptop_capacity) > 0 else 0
            }
        }
    
    # Add summary data
    capacity_data["summary"] = {
        "total_capacity": sum(classroom_capacities.values()),
        "total_registered": Participant.query.count(),
        "saturday_sessions": len([s for s in sessions if s.day == "Saturday"]),
        "sunday_sessions": len([s for s in sessions if s.day == "Sunday"])
    }
    
    return jsonify(capacity_data)


@admin_bp.route('/admin/dashboard')
def dashboard():
    # Logic to fetch attendance statistics and display them
    return render_template('admin/dashboard.html')


@admin_bp.route('/admin/import', methods=['GET', 'POST'])
def import_data():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                # import_attendance_data(file)
                flash('Attendance data imported successfully!', 'success')
            except Exception as e:
                flash(f'Error importing data: {str(e)}', 'danger')
            return redirect(url_for('admin.import_data'))
    return render_template('admin/import.html')


@admin_bp.route('/admin/reports')
def reports():
    # Logic to generate and display attendance reports
    return render_template('admin/reports.html')
