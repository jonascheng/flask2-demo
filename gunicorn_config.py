import os
import app as app_module

bind = '0.0.0.0:5000'

workers = 2
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')

preload_app = False

timeout = 1200
threads = 1
keepalive = 60 * 4

def post_fork(server, worker):
    app_module.post_fork_init()
