import os

# cPanel Passenger looks for a module-level `application`.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "roshe_logistics.settings")

from roshe_logistics.wsgi import application  # noqa: E402
