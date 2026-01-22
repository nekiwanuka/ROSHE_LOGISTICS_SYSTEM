from __future__ import annotations

from .permissions import get_app_permissions


def app_permissions(request):
    """Expose app permission flags to all templates as `app_perms`."""
    return {'app_perms': get_app_permissions(getattr(request, 'user', None))}
