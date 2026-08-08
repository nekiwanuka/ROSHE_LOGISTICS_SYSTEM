from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.utils import timezone


class GenericNotFoundMiddleware:
    """Replace technical 404 responses with the public not-found page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 404:
            return render(request, "404.html", status=404)
        return response


class BlockAdminForManagingDirectorMiddleware:
    """Prevent Managing Director users from accessing Django admin (/admin/)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = (getattr(request, "path_info", None) or request.path or "").lower()
        if path.startswith("/admin"):
            user = getattr(request, "user", None)
            if (
                getattr(user, "is_authenticated", False)
                and getattr(user, "role", None) == "managing_director"
            ):
                # System admin (true Django superuser) is not blocked.
                if not getattr(user, "is_superuser", False):
                    messages.error(request, "Permission denied")
                    return redirect("dashboard")

        return self.get_response(request)


class AbsoluteSessionExpiryMiddleware:
    """Force logout after a fixed duration from login.

    Django's SESSION_COOKIE_AGE can behave like a sliding expiry if the session
    gets modified frequently (e.g., messages). This middleware enforces an
    absolute timeout from the moment the user completed login.
    """

    SESSION_KEY = "login_ts"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False):
            try:
                login_ts = float(request.session.get(self.SESSION_KEY) or 0)
            except Exception:
                login_ts = 0

            if login_ts:
                age_seconds = timezone.now().timestamp() - login_ts
                # Keep aligned with settings.SESSION_COOKIE_AGE (= 3600).
                if age_seconds > 60 * 60:
                    logout(request)
                    try:
                        request.session.pop(self.SESSION_KEY, None)
                    except Exception:
                        pass
                    messages.error(request, "Session expired. Please login again.")
                    return redirect("login")

        return self.get_response(request)
