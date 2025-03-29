import multiprocessing

# Server Socket
bind = "127.0.0.1:8000"  # Only accessible locally, NGINX will proxy requests

# Worker Settings
# workers = multiprocessing.cpu_count() * 2 + 1  # Efficient worker count
workers = 5
threads = 2  # Each worker handles 2 threads for concurrency
worker_class = "gthread"  # Threaded workers for better async handling

# Security & Performance
timeout = 120  # Prevent timeouts for long requests
graceful_timeout = 90  # Allow workers to finish before restarting
keepalive = 5  # Keep connections open for faster requests
max_requests = 1000  # Restart workers after processing 1000 requests (memory leak protection)
max_requests_jitter = 50  # Staggered restarts to avoid downtime

# Logging
accesslog = "/home/academy/km120/attendance_tracking/log/gunicorn/access.log"
errorlog = "/home/academy/km120/attendance_tracking/log/gunicorn/error.log"
loglevel = "info"

# Process Name
proc_name = "ahancha_gunicorn"
