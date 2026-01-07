from django.contrib import messages
from django.shortcuts import redirect


class BlockAdminForManagingDirectorMiddleware:
    """Prevent Managing Director users from accessing Django admin (/admin/)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = (getattr(request, "path_info", None) or request.path or "").lower()
        if path.startswith("/admin"):
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False) and getattr(user, "role", None) == "managing_director":
                # System admin (true Django superuser) is not blocked.
                if not getattr(user, "is_superuser", False):
                    messages.error(request, "Permission denied")
                    return redirect("dashboard")

        return self.get_response(request)
