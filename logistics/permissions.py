"""Centralized permission logic.

This project uses role-based access control with optional per-user overrides.
Overrides are set by privileged admins during user creation.
"""

from __future__ import annotations

from typing import Dict


PERM_KEYS = {
    'manage_users',
    'create_clients',
    'create_quotations',
    'create_invoices',
    'create_receipts',
    'access_reports',
    'view_revenue',
    'edit_delete_documents',
    'approve_verify_receipts',
    'void_unvoid_receipts',
}


ROLE_DEFAULTS: Dict[str, Dict[str, bool]] = {
    'superuser': {
        'manage_users': True,
        'create_clients': True,
        'create_quotations': True,
        'create_invoices': True,
        'create_receipts': True,
        'access_reports': True,
        'view_revenue': True,
        'edit_delete_documents': True,
        'approve_verify_receipts': False,
        'void_unvoid_receipts': False,
    },
    'managing_director': {
        'manage_users': True,
        'create_clients': True,
        'create_quotations': True,
        'create_invoices': True,
        'create_receipts': True,
        'access_reports': True,
        'view_revenue': True,
        'edit_delete_documents': True,
        'approve_verify_receipts': True,
        'void_unvoid_receipts': True,
    },
    'manager': {
        'manage_users': True,
        'create_clients': True,
        'create_quotations': True,
        'create_invoices': True,
        'create_receipts': True,
        'access_reports': True,
        'view_revenue': False,
        'edit_delete_documents': False,
        'approve_verify_receipts': False,
        'void_unvoid_receipts': False,
    },
    'accountant': {
        'manage_users': False,
        'create_clients': False,
        'create_quotations': True,
        'create_invoices': True,
        'create_receipts': True,
        'access_reports': True,
        'view_revenue': False,
        'edit_delete_documents': False,
        'approve_verify_receipts': True,
        'void_unvoid_receipts': True,
    },
    # Front Desk Operator
    'data_entry': {
        'manage_users': False,
        'create_clients': True,
        'create_quotations': True,
        'create_invoices': True,
        'create_receipts': True,
        'access_reports': False,
        'view_revenue': False,
        'edit_delete_documents': False,
        'approve_verify_receipts': False,
        'void_unvoid_receipts': False,
    },
}


def get_app_permissions(user) -> Dict[str, bool]:
    """Return effective permissions for a user."""
    if not user or not getattr(user, 'is_authenticated', False):
        return {k: False for k in PERM_KEYS}

    role = getattr(user, 'role', None) or ('superuser' if bool(getattr(user, 'is_superuser', False)) else 'data_entry')
    base = dict(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS['data_entry']))

    overrides = getattr(user, 'permission_overrides', None) or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key in PERM_KEYS and value is not None:
                base[key] = bool(value)

    # Safety invariants: MD always retains MD privileges.
    if role == 'managing_director':
        for key in (
            'manage_users',
            'access_reports',
            'view_revenue',
            'edit_delete_documents',
            'approve_verify_receipts',
            'void_unvoid_receipts',
        ):
            base[key] = True

    # Policy: only Managing Director and Accountant may approve/void receipts.
    if role in {'managing_director', 'accountant'}:
        base['approve_verify_receipts'] = True
        base['void_unvoid_receipts'] = True
    else:
        base['approve_verify_receipts'] = False
        base['void_unvoid_receipts'] = False

    return base


def has_app_permission(user, key: str) -> bool:
    return bool(get_app_permissions(user).get(key, False))
