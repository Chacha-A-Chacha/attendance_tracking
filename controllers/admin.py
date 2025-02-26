from flask import Blueprint, render_template, request, redirect, url_for, flash
from models.participant import Participant
from models.attendance import Attendance
from services.importer import import_attendance_data

admin_bp = Blueprint('admin', __name__)

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
                import_attendance_data(file)
                flash('Attendance data imported successfully!', 'success')
            except Exception as e:
                flash(f'Error importing data: {str(e)}', 'danger')
            return redirect(url_for('admin.import_data'))
    return render_template('admin/import.html')

@admin_bp.route('/admin/reports')
def reports():
    # Logic to generate and display attendance reports
    return render_template('admin/reports.html')