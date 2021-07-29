# import os

# if os.environ.get('GUNICORN_WORKER_CLASS', 'gthread') == 'gevent':
#   from gevent import monkey
#   monkey.patch_all()

import app as app_module
app = app_module.create_app()
