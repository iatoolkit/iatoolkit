"""One boot process avoids concurrent schema initialization on a fresh database."""

bind = '0.0.0.0:8000'
workers = 1
worker_class = 'gthread'
threads = 8
timeout = 180
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
capture_output = True
