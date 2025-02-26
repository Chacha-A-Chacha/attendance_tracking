from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from services.importer import import_spreadsheet
import os

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
