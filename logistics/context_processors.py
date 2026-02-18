from __future__ import annotations

from .permissions import get_app_permissions
from .models import PaymentTransaction


def app_permissions(request):
    """Expose app permission flags to all templates as `app_perms`."""
    user = getattr(request, 'user', None)
    perms = get_app_permissions(user)

    pending_verification_count = 0
    if perms.get('approve_verify_receipts', False):
        pending_verification_count = PaymentTransaction.objects.filter(
            verification_status='pending',
            is_voided=False,
        ).count()

    return {
        'app_perms': perms,
        'pending_verification_count': pending_verification_count,
    }
