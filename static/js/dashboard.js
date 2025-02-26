// filepath: /attendance_tracking/static/js/dashboard.js
document.addEventListener('DOMContentLoaded', function() {
    // Initialize dashboard elements
    const attendanceStats = document.getElementById('attendance-stats');
    const recentActivity = document.getElementById('recent-activity');

    // Fetch attendance statistics from the server
    function fetchAttendanceStats() {
        fetch('/api/attendance/stats')
            .then(response => response.json())
            .then(data => {
                attendanceStats.innerHTML = `
                    <h3>Attendance Statistics</h3>
                    <p>Total Participants: ${data.totalParticipants}</p>
                    <p>Total Sessions: ${data.totalSessions}</p>
                    <p>Attendance Rate: ${data.attendanceRate}%</p>
                `;
            })
            .catch(error => console.error('Error fetching attendance stats:', error));
    }

    // Fetch recent activity logs
    function fetchRecentActivity() {
        fetch('/api/attendance/recent-activity')
            .then(response => response.json())
            .then(data => {
                recentActivity.innerHTML = '<h3>Recent Activity</h3>';
                data.forEach(activity => {
                    const activityItem = document.createElement('p');
                    activityItem.textContent = `${activity.timestamp}: ${activity.description}`;
                    recentActivity.appendChild(activityItem);
                });
            })
            .catch(error => console.error('Error fetching recent activity:', error));
    }

    // Initialize dashboard data
    fetchAttendanceStats();
    fetchRecentActivity();
});