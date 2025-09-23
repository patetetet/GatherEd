"""
WSGI config for gather_ed project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gather_ed.settings')

application = get_wsgi_application()