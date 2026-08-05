"""Views for the logistics management system."""

import csv
import logging
import re
import json
from decimal import Decimal
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import quote
from xml.sax.saxutils import escape

from django.contrib import messages
from django.core.management import call_command
from django.core.mail import EmailMessage
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum, ProtectedError
from django.db.models.deletion import PROTECT
from django.conf import settings
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .forms import (
    ClientForm,
    ContainerReturnForm,
    LoadingForm,
    PaymentForm,
    PaymentTransactionForm,
    QuoteForm,
    SendDocumentEmailForm,
    TransitForm,
    UserRegistrationForm,
    UserDetailsUpdateForm,
    UserRoleUpdateForm,
    UserPermissionOverridesForm,
)
from .models import (
    AuditLog,
    Client,
    ContainerReturn,
    CustomUser,
    Loading,
    Payment,
    PaymentTransaction,
    Quote,
    Transit,
)

from .permissions import ROLE_DEFAULTS, get_app_permissions, has_app_permission
from .whatsapp_api import send_whatsapp_document

logger = logging.getLogger(__name__)


DEFAULT_PAGE_SIZE = 20


def _reassign_protected_user_references(*, from_user, to_user):
    """Reassign PROTECT foreign keys pointing at a user.

    This is used to support hard-deleting users while preserving historical records.
    Only relations within the `logistics` app are touched.
    """
    if not from_user or not to_user or from_user.pk == to_user.pk:
        return 0, []

    reassigned_total = 0
    touched = []

    for rel in from_user._meta.related_objects:
        field = getattr(rel, "field", None)
        if field is None:
            continue

        remote_field = getattr(field, "remote_field", None)
        if remote_field is None:
            continue

        on_delete = getattr(remote_field, "on_delete", None)
        related_model = getattr(rel, "related_model", None)
        if on_delete is not PROTECT or related_model is None:
            continue

        if (
            getattr(getattr(related_model, "_meta", None), "app_label", None)
            != "logistics"
        ):
            continue

        field_name = field.name
        qs = related_model._default_manager.filter(**{field_name: from_user})
        updated = qs.update(**{field_name: to_user})
        if updated:
            reassigned_total += int(updated)
            touched.append(f"{related_model.__name__}.{field_name}:{updated}")

    return reassigned_total, touched


AUDIT_PAGE_SIZE = 40


FULL_ACCESS_ROLES = {"superuser", "managing_director"}


USER_ADMIN_ROLES = {"superuser", "managing_director", "manager"}


def _can_manage_users(user) -> bool:
    return has_app_permission(user, "manage_users")


def _can_view_revenue(user) -> bool:
    return has_app_permission(user, "view_revenue")


def _finalize_login(request, user):
    """Complete login and set absolute session expiry timestamp."""
    login(request, user)
    request.session["login_ts"] = timezone.now().timestamp()
    try:
        request.session.set_expiry(getattr(settings, "SESSION_COOKIE_AGE", 60 * 60))
    except Exception:
        pass


def _has_full_app_access(user) -> bool:
    """Full in-app access (System Admin + Managing Director)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) in FULL_ACCESS_ROLES


def _can_create_clients(user) -> bool:
    return has_app_permission(user, "create_clients")


def _deny_if_data_entry_reports(request):
    """Users without reports access cannot access reports/exports."""
    if not has_app_permission(getattr(request, "user", None), "access_reports"):
        return HttpResponse("Permission denied", status=403)
    return None


def _fmt_dt(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _fmt_number(value, decimals=2):
    if value is None or value == "":
        return ""
    try:
        return f"{Decimal(str(value)):.{decimals}f}"
    except Exception:
        try:
            return f"{float(value):.{decimals}f}"
        except Exception:
            return str(value)


def _normalize_whatsapp_phone(raw_value, default_country_code="256"):
    if raw_value is None:
        return ""

    digits = re.sub(r"\D", "", str(raw_value))
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = f"{default_country_code}{digits[1:]}"
    elif len(digits) == 9:
        digits = f"{default_country_code}{digits}"

    return digits


def _whatsapp_share_url(*, phone, message):
    safe_phone = _normalize_whatsapp_phone(phone)
    recipient = safe_phone or "256773183916"
    return f"https://wa.me/{recipient}?text={quote(message or '')}"


def _whatsapp_app_url(*, phone, message):
    safe_phone = _normalize_whatsapp_phone(phone)
    recipient = safe_phone or "256773183916"
    return f"whatsapp://send?phone={recipient}&text={quote(message or '')}"


def _log_whatsapp_share(*, model_type, object_id, label, recipient_phone, user):
    normalized = _normalize_whatsapp_phone(recipient_phone) or "unknown"
    log_audit(model_type, "update", object_id, f"[WA] {label} -> {normalized}", user)


def _is_whatsapp_api_mode_enabled():
    return str(getattr(settings, "WHATSAPP_MODE", "link")).strip().lower() == "api"


def _fmt_money(value):
    if value is None or value == "":
        return ""
    try:
        return f"${Decimal(str(value)):,.2f}"
    except Exception:
        return str(value)


def _quote_number(quote):
    if getattr(quote, "pk", None):
        return f"QTN-{quote.pk:05d}"
    return "QTN-DRAFT"


def _numeric_part(value, default=None):
    if value is None:
        return default
    try:
        import re

        match = re.search(r"(\d+)(?!.*\d)", str(value))
        if match:
            return match.group(1)
    except Exception:
        return default
    return default


def _draw_brand_footer(canvas_obj, doc, primary, accent):
    """Draw a branded footer: yellow background with blue text."""
    width, _ = doc.pagesize
    left = doc.leftMargin
    right = width - doc.rightMargin

    footer_h = 22
    y0 = 0

    canvas_obj.saveState()
    canvas_obj.setFillColor(accent)
    canvas_obj.rect(0, y0, width, footer_h, fill=1, stroke=0)

    canvas_obj.setFillColor(primary)
    canvas_obj.setFont("Helvetica-Bold", 8.5)
    canvas_obj.drawString(left, y0 + 7, "ROSHE LOGISTICS")

    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawRightString(right, y0 + 7, "www.roshegroup.com")
    canvas_obj.restoreState()


def _draw_svg_logo_in_box(
    *,
    canvas_obj,
    left: float,
    top: float,
    primary,
    box_size: float = 44,
    desired_h: float = 34,
):
    """Draw the Roshe SVG logo inside a colored square.

    In production this requires the `svglib` dependency to be installed.
    """
    canvas_obj.saveState()
    canvas_obj.setFillColor(primary)
    canvas_obj.rect(left, top - box_size + 8, box_size, box_size, fill=1, stroke=0)

    logo_path = finders.find("images/roshe_logo.svg")
    if not logo_path:
        logger.warning("PDF logo not found in staticfiles: images/roshe_logo.svg")
        canvas_obj.restoreState()
        return

    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF

        drawing = svg2rlg(logo_path)
        if drawing and drawing.height:
            scale = desired_h / float(drawing.height)
            drawing.scale(scale, scale)
            renderPDF.draw(drawing, canvas_obj, left + 5, top - desired_h + 10)
    except Exception:
        # Don't break PDF generation if branding can't be rendered.
        logger.exception(
            "Failed to render PDF logo from %s. Ensure `svglib` is installed on the host.",
            logo_path,
        )
    finally:
        canvas_obj.restoreState()


# ===== AUTHENTICATION =====


def login_view(request):
    """Authenticate user credentials and start a session."""
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            _finalize_login(request, user)
            return redirect("dashboard")
        messages.error(request, "Invalid username or password")
    return render(request, "logistics/login.html")


def logout_view(request):
    """Terminate an authenticated session."""
    logout(request)
    messages.success(request, "Logged out successfully")
    return redirect("login")


def register_view(request):
    """Create new user accounts based on role hierarchy."""
    if not request.user.is_authenticated:
        return redirect("login")
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    role_permissions = {
        "superuser": {
            "label": "Superuser",
            "manage_users": True,
            "manage_users_note": "Full (can create Managing Director and all roles).",
            "create_clients": True,
            "create_quotations": True,
            "create_invoices": True,
            "create_receipts": True,
            "print_statements": True,
            "edit_delete_documents": True,
            "approve_verify_receipts": False,
            "void_unvoid_receipts": False,
            "view_revenue": True,
            "access_reports": True,
        },
        "managing_director": {
            "label": "Managing Director",
            "manage_users": True,
            "manage_users_note": "Full (can create Manager, Accountant, Front Desk).",
            "create_clients": True,
            "create_quotations": True,
            "create_invoices": True,
            "create_receipts": True,
            "print_statements": True,
            "edit_delete_documents": True,
            "approve_verify_receipts": True,
            "void_unvoid_receipts": True,
            "view_revenue": True,
            "access_reports": True,
        },
        "manager": {
            "label": "Manager",
            "manage_users": True,
            "manage_users_note": "Limited (can create Accountant and Front Desk; can view only those users).",
            "create_clients": True,
            "create_quotations": True,
            "create_invoices": True,
            "create_receipts": True,
            "print_statements": True,
            "edit_delete_documents": False,
            "approve_verify_receipts": False,
            "void_unvoid_receipts": False,
            "view_revenue": False,
            "access_reports": True,
        },
        "accountant": {
            "label": "Accountant",
            "manage_users": False,
            "manage_users_note": "No",
            "create_clients": False,
            "create_quotations": True,
            "create_invoices": True,
            "create_receipts": True,
            "print_statements": True,
            "edit_delete_documents": False,
            "approve_verify_receipts": True,
            "void_unvoid_receipts": True,
            "view_revenue": False,
            "access_reports": True,
        },
        "data_entry": {
            "label": "Front Desk Operator",
            "manage_users": False,
            "manage_users_note": "No",
            "create_clients": True,
            "create_quotations": True,
            "create_invoices": True,
            "create_receipts": True,
            "print_statements": True,
            "edit_delete_documents": False,
            "approve_verify_receipts": False,
            "void_unvoid_receipts": False,
            "view_revenue": False,
            "access_reports": False,
        },
    }
    if request.method == "POST":
        form = UserRegistrationForm(
            request.POST,
            request_user=request.user,
            can_configure_permissions=_has_full_app_access(request.user),
        )
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} created successfully")
            log_audit("user", "create", user.id, str(user), request.user)
            return redirect("user_list")
    else:
        form = UserRegistrationForm(
            request_user=request.user,
            can_configure_permissions=_has_full_app_access(request.user),
        )
    return render(
        request,
        "logistics/register.html",
        {
            "form": form,
            "role_permissions": role_permissions,
            "can_configure_permissions": _has_full_app_access(request.user),
        },
    )


# ===== DASHBOARD & USERS =====


@login_required
def dashboard(request):
    """Landing page with KPI highlights."""
    context = {
        "total_clients": Client.objects.count(),
        "total_loadings": Loading.objects.count(),
        "total_transits": Transit.objects.count(),
        "outstanding_payments": Payment.objects.filter(balance__gt=0).aggregate(
            Sum("balance")
        )["balance__sum"]
        or 0,
        "recent_clients": Client.objects.all()[:5],
        "recent_loadings": Loading.objects.all()[:5],
        "pending_containers": ContainerReturn.objects.filter(status="pending").count(),
        "pending_verifications": PaymentTransaction.objects.filter(
            verification_status="pending"
        ).count(),
        "enable_seed_tools": getattr(settings, "ENABLE_SEED_TOOLS", False),
    }
    return render(request, "logistics/dashboard.html", context)


@login_required
def global_search(request):
    query = (request.GET.get("q") or "").strip()

    results = {
        "clients": [],
        "loadings": [],
        "transits": [],
        "payments": [],
        "receipts": [],
        "quotes": [],
        "containers": [],
        "users": [],
    }

    if query:
        results["clients"] = list(
            Client.objects.filter(
                Q(client_id__icontains=query)
                | Q(name__icontains=query)
                | Q(contact_person__icontains=query)
                | Q(company_name__icontains=query)
                | Q(phone__icontains=query)
            ).order_by("-created_at", "-pk")[:8]
        )

        results["loadings"] = list(
            Loading.objects.select_related("client")
            .filter(
                Q(container_number__icontains=query)
                | Q(client__name__icontains=query)
                | Q(client__client_id__icontains=query)
                | Q(origin__icontains=query)
                | Q(destination__icontains=query)
                | Q(item_description__icontains=query)
            )
            .order_by("-created_at", "-pk")[:8]
        )

        results["transits"] = list(
            Transit.objects.filter(
                Q(container_number__icontains=query)
                | Q(shipping_line__icontains=query)
                | Q(remarks__icontains=query)
                | Q(status__icontains=query)
                | Q(eta_location__icontains=query)
            ).order_by("-created_at", "-pk")[:8]
        )

        results["payments"] = list(
            Payment.objects.select_related("loading__client")
            .filter(
                Q(receipt_number__icontains=query)
                | Q(loading__container_number__icontains=query)
                | Q(loading__client__name__icontains=query)
                | Q(loading__client__client_id__icontains=query)
            )
            .order_by("-created_at", "-pk")[:8]
        )

        receipt_filters = (
            Q(reference__icontains=query)
            | Q(payment__loading__container_number__icontains=query)
            | Q(payment__loading__client__name__icontains=query)
            | Q(payment__loading__client__client_id__icontains=query)
            | Q(notes__icontains=query)
        )
        receipt_id_text = _numeric_part(query)
        if receipt_id_text and receipt_id_text.isdigit():
            receipt_filters |= Q(pk=int(receipt_id_text))

        results["receipts"] = list(
            PaymentTransaction.objects.select_related("payment__loading__client")
            .filter(receipt_filters)
            .order_by("-created_at", "-pk")[:8]
        )

        results["quotes"] = list(
            Quote.objects.select_related("client", "loading")
            .filter(
                Q(container_number__icontains=query)
                | Q(client__name__icontains=query)
                | Q(client__client_id__icontains=query)
                | Q(origin__icontains=query)
                | Q(destination__icontains=query)
                | Q(notes__icontains=query)
            )
            .order_by("-created_at", "-pk")[:8]
        )

        results["containers"] = list(
            ContainerReturn.objects.select_related("loading__client")
            .filter(
                Q(container_number__icontains=query)
                | Q(loading__container_number__icontains=query)
                | Q(loading__client__name__icontains=query)
                | Q(loading__client__client_id__icontains=query)
                | Q(status__icontains=query)
                | Q(condition__icontains=query)
                | Q(remarks__icontains=query)
            )
            .order_by("-created_at", "-pk")[:8]
        )

        if _can_manage_users(request.user):
            users_qs = CustomUser.objects.all().order_by("-created_at", "-id")
            if getattr(request.user, "role", None) == "manager" and not getattr(
                request.user, "is_superuser", False
            ):
                users_qs = users_qs.filter(role__in={"accountant", "data_entry"})
            results["users"] = list(
                users_qs.filter(
                    Q(username__icontains=query)
                    | Q(email__icontains=query)
                    | Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(phone__icontains=query)
                )[:8]
            )

    total_results = sum(len(items) for items in results.values())
    context = {
        "query": query,
        "results": results,
        "total_results": total_results,
    }
    return render(request, "logistics/search_results.html", context)


@login_required
def dashboard_reset_keep_users_and_seed(request):
    if not getattr(settings, "ENABLE_SEED_TOOLS", False):
        # Hide existence of this endpoint in production.
        raise Http404()

    if not getattr(request.user, "is_superuser", False):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    if request.method != "POST":
        return redirect("dashboard")

    username = (request.POST.get("created_by") or "").strip()
    if not username:
        messages.error(request, "Please enter a username to own the seeded records.")
        return redirect("dashboard")

    if not CustomUser.objects.filter(username=username).exists():
        messages.error(request, f"User '{username}' not found.")
        return redirect("dashboard")

    try:
        call_command("reset_keep_users_and_seed", yes=True, created_by=username)
    except Exception as exc:
        messages.error(request, f"Failed to reset & reseed: {exc}")
        return redirect("dashboard")

    messages.success(
        request, f"Database reset and sample data reseeded (owner: {username})."
    )
    return redirect("dashboard")


@login_required
def user_list(request):
    """List all users (superusers only)."""
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    users = CustomUser.objects.all().order_by("-created_at", "-id")

    search = (request.GET.get("search") or "").strip()
    role_filter = (request.GET.get("role") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    if getattr(request.user, "role", None) == "manager" and not getattr(
        request.user, "is_superuser", False
    ):
        users = users.filter(role__in={"accountant", "data_entry"})

    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
        )

    if role_filter:
        users = users.filter(role=role_filter)

    if status_filter in {"active", "inactive"}:
        users = users.filter(is_active=(status_filter == "active"))

    page_obj, query_string, page_range = paginate_queryset(request, users)
    return render(
        request,
        "logistics/users/list.html",
        {
            "users": page_obj,
            "search": search,
            "role_filter": role_filter,
            "status_filter": status_filter,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def user_permissions_update(request, pk):
    """MD/superuser can grant/revoke per-user feature permissions."""
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    # Only MD/superuser should be able to change feature checkboxes.
    is_privileged_editor = bool(
        getattr(request.user, "is_superuser", False)
    ) or getattr(request.user, "role", None) in {"superuser", "managing_director"}
    if not is_privileged_editor:
        messages.error(request, "Only the Managing Director can edit user permissions.")
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    # Managers can only see a subset in user_list already, but enforce again.
    if getattr(request.user, "role", None) == "manager" and not getattr(
        request.user, "is_superuser", False
    ):
        if getattr(target_user, "role", None) not in {"accountant", "data_entry"}:
            messages.error(request, "Permission denied")
            return redirect("user_list")

    if bool(getattr(target_user, "is_superuser", False)) and not bool(
        getattr(request.user, "is_superuser", False)
    ):
        messages.error(
            request, "Only a Django superuser can modify a superuser account."
        )
        return redirect("user_list")

    if bool(getattr(target_user, "is_superuser", False)) and not bool(
        getattr(request.user, "is_superuser", False)
    ):
        messages.error(request, "Only a Django superuser can edit a superuser account.")
        return redirect("user_list")

    if request.method == "POST":
        form = UserPermissionOverridesForm(request.POST, user=target_user)
        if form.is_valid():
            role = getattr(target_user, "role", None) or "data_entry"
            defaults = ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["data_entry"])

            desired = {
                key: bool(form.cleaned_data.get(key, False))
                for key in (
                    "manage_users",
                    "create_clients",
                    "create_quotations",
                    "create_invoices",
                    "create_receipts",
                    "access_reports",
                    "view_revenue",
                    "approve_verify_receipts",
                    "void_unvoid_receipts",
                )
            }

            # Store only the differences from role defaults.
            overrides = {
                key: value
                for key, value in desired.items()
                if key in defaults and bool(defaults.get(key, False)) != bool(value)
            }

            target_user.permission_overrides = overrides
            target_user.save(update_fields=["permission_overrides"])
            messages.success(
                request, f"Permissions updated for {target_user.username}."
            )
            log_audit(
                "user",
                "permissions_update",
                target_user.id,
                target_user.username,
                request.user,
            )
            return redirect("user_list")
    else:
        form = UserPermissionOverridesForm(user=target_user)

    role = getattr(target_user, "role", None) or "data_entry"
    role_defaults = ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["data_entry"])
    effective = get_app_permissions(target_user)

    return render(
        request,
        "logistics/users/permissions.html",
        {
            "target_user": target_user,
            "form": form,
            "role_defaults": role_defaults,
            "effective_permissions": effective,
            "current_overrides": target_user.permission_overrides or {},
        },
    )


@login_required
def user_update_details(request, pk):
    """Superuser/Managing Director can edit user account details."""
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    is_privileged_editor = bool(
        getattr(request.user, "is_superuser", False)
    ) or getattr(request.user, "role", None) in {"superuser", "managing_director"}
    if not is_privileged_editor:
        messages.error(
            request, "Only Admin or Managing Director can edit user details."
        )
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    if bool(getattr(target_user, "is_superuser", False)) and not bool(
        getattr(request.user, "is_superuser", False)
    ):
        messages.error(request, "Only Admin can edit an admin account.")
        return redirect("user_list")

    if request.method == "POST":
        form = UserDetailsUpdateForm(request.POST, instance=target_user)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"User details updated for {target_user.username}."
            )
            log_audit(
                "user",
                "update",
                target_user.id,
                f"Details updated: {target_user.username}",
                request.user,
            )
            return redirect("user_list")
    else:
        form = UserDetailsUpdateForm(instance=target_user)

    return render(
        request,
        "logistics/users/details.html",
        {
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
def user_change_password(request, pk):
    """Superuser/Managing Director can set a user's password."""
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    is_privileged_editor = bool(
        getattr(request.user, "is_superuser", False)
    ) or getattr(request.user, "role", None) in {"superuser", "managing_director"}
    if not is_privileged_editor:
        messages.error(
            request, "Only Admin or Managing Director can change user passwords."
        )
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    if bool(getattr(target_user, "is_superuser", False)) and not bool(
        getattr(request.user, "is_superuser", False)
    ):
        messages.error(request, "Only Admin can change an admin password.")
        return redirect("user_list")

    if request.method == "POST":
        form = SetPasswordForm(user=target_user, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Password updated for {target_user.username}.")
            log_audit(
                "user",
                "update",
                target_user.id,
                f"Password updated: {target_user.username}",
                request.user,
            )
            return redirect("user_list")
    else:
        form = SetPasswordForm(user=target_user)

    return render(
        request,
        "logistics/users/change_password.html",
        {
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
def user_role_update(request, pk):
    """MD/superuser can update a user's role."""
    if not _can_manage_users(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")

    is_privileged_editor = bool(
        getattr(request.user, "is_superuser", False)
    ) or getattr(request.user, "role", None) in {"superuser", "managing_director"}
    if not is_privileged_editor:
        messages.error(request, "Only Admin or Managing Director can edit user roles.")
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    if target_user.pk == request.user.pk:
        messages.error(request, "You cannot change your own role from here.")
        return redirect("user_list")

    if bool(getattr(target_user, "is_superuser", False)):
        # Role is derived from is_superuser in CustomUser.save().
        messages.error(
            request,
            "This account is a Django superuser. Its role is managed automatically.",
        )
        return redirect("user_list")

    if request.method == "POST":
        form = UserRoleUpdateForm(
            request.POST, request_user=request.user, target_user=target_user
        )
        if form.is_valid():
            old_role = getattr(target_user, "role", None)
            new_role = form.cleaned_data["role"]

            if old_role == new_role:
                messages.info(request, "No changes were made.")
                return redirect("user_list")

            target_user.role = new_role

            # Privileged account types have fixed permissions; clear overrides.
            if new_role in {"superuser", "managing_director"}:
                target_user.permission_overrides = {}

            target_user.save(update_fields=["role", "permission_overrides"])
            messages.success(request, f"Role updated for {target_user.username}.")
            log_audit(
                "user",
                "role_update",
                target_user.id,
                f"{target_user.username}: {old_role} -> {new_role}",
                request.user,
            )
            return redirect("user_list")
    else:
        form = UserRoleUpdateForm(request_user=request.user, target_user=target_user)

    return render(
        request,
        "logistics/users/role.html",
        {
            "target_user": target_user,
            "form": form,
        },
    )


@login_required
def user_login_as(request, pk):
    """Allow Superuser/Managing Director to sign in as another user."""
    if request.method != "POST":
        return redirect("user_list")

    actor = request.user
    actor_is_superuser = bool(getattr(actor, "is_superuser", False))
    actor_is_md = getattr(actor, "role", None) == "managing_director"
    if not (actor_is_superuser or actor_is_md):
        messages.error(request, "Permission denied")
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    if target_user.pk == actor.pk:
        messages.error(request, "You are already signed in as this user.")
        return redirect("user_list")

    if actor_is_md and (
        bool(getattr(target_user, "is_superuser", False))
        or getattr(target_user, "role", None) == "superuser"
    ):
        messages.error(request, "Managing Director cannot login as Admin users.")
        return redirect("user_list")

    if not bool(getattr(target_user, "is_active", False)):
        messages.error(request, "Cannot login as an inactive user.")
        return redirect("user_list")

    _finalize_login(request, target_user)
    log_audit(
        "user",
        "update",
        target_user.id,
        f"Login-as: {actor.username} -> {target_user.username}",
        actor,
    )
    messages.success(request, f"You are now signed in as {target_user.username}.")
    return redirect("dashboard")


@login_required
def user_delete(request, pk):
    """Delete a user account (Django superusers only).

    This intentionally allows deleting other superusers as requested, but:
    - prevents deleting yourself
    - prevents deleting the last remaining Django superuser
    """
    if not bool(getattr(request.user, "is_superuser", False)):
        messages.error(request, "Permission denied")
        return redirect("user_list")

    target_user = get_object_or_404(CustomUser, pk=pk)

    if target_user.pk == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect("user_list")

    if request.method != "POST":
        return redirect("user_list")

    if bool(getattr(target_user, "is_superuser", False)):
        remaining_superusers = (
            CustomUser.objects.filter(is_superuser=True)
            .exclude(pk=target_user.pk)
            .count()
        )
        if remaining_superusers <= 0:
            messages.error(request, "Cannot delete the last remaining superuser.")
            return redirect("user_list")

    username = target_user.username
    try:
        with transaction.atomic():
            reassigned_total, touched = _reassign_protected_user_references(
                from_user=target_user,
                to_user=request.user,
            )

            try:
                target_user.delete()
            except ProtectedError:
                # Still blocked (e.g., non-logistics relations). Fall back to deactivation.
                if hasattr(target_user, "is_active"):
                    if target_user.is_active:
                        target_user.is_active = False
                        target_user.save(update_fields=["is_active"])
                        messages.warning(
                            request,
                            f"User {username} cannot be fully deleted because they are referenced by existing records. "
                            "Their records were reassigned where possible and the account was deactivated.",
                        )
                        log_audit("user", "deactivate", pk, username, request.user)
                    else:
                        messages.warning(
                            request,
                            f"User {username} cannot be fully deleted because they are referenced by existing records. "
                            "Their records were reassigned where possible and the account is already deactivated.",
                        )
                else:
                    messages.error(
                        request,
                        f"User {username} cannot be deleted because they are referenced by existing records.",
                    )
                return redirect("user_list")

    except IntegrityError:
        messages.error(
            request,
            "Unable to reassign this user's records due to a data integrity constraint. "
            "No changes were applied.",
        )
        return redirect("user_list")

    if reassigned_total:
        messages.info(
            request,
            f"Reassigned {reassigned_total} record(s) to {request.user.username}.",
        )
        log_audit(
            "user",
            "reassign",
            pk,
            f"{username} -> {request.user.username} ({reassigned_total})",
            request.user,
        )

    messages.success(request, f"User {username} deleted successfully.")
    log_audit("user", "delete", pk, username, request.user)
    return redirect("user_list")


# ===== CLIENT MANAGEMENT =====


@login_required
def client_list(request):
    clients = Client.objects.all()
    search = request.GET.get("search", "")
    if search:
        clients = clients.filter(
            Q(client_id__icontains=search)
            | Q(name__icontains=search)
            | Q(contact_person__icontains=search)
        )
    page_obj, query_string, page_range = paginate_queryset(request, clients)
    return render(
        request,
        "logistics/clients/list.html",
        {
            "clients": page_obj,
            "search": search,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def client_create(request):
    if not has_app_permission(request.user, "create_clients"):
        messages.error(request, "Permission denied")
        return redirect("client_list")
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            client.created_by = request.user
            client.save()
            messages.success(request, f"Client {client.name} created successfully")
            log_audit("client", "create", client.id, str(client), request.user)
            return redirect("client_detail", pk=client.id)
    else:
        form = ClientForm()
    return render(
        request,
        "logistics/clients/form.html",
        {"form": form, "title": "Create Client"},
    )


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    return render(
        request,
        "logistics/clients/detail.html",
        {"client": client, "loadings": client.loadings.all()},
    )


@login_required
def client_update(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("client_list")
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, "Client updated successfully")
            log_audit("client", "update", client.id, str(client), request.user)
            return redirect("client_detail", pk=client.id)
    else:
        form = ClientForm(instance=client)
    return render(
        request,
        "logistics/clients/form.html",
        {"form": form, "title": "Update Client", "client": client},
    )


@login_required
def client_delete(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("client_list")
    client = get_object_or_404(Client, pk=pk)
    client_str = str(client)
    client_id = client.id
    try:
        client.delete()
    except ProtectedError:
        messages.error(
            request,
            "This client cannot be deleted while there are cargo/loadings linked to them. Remove or reassign those records first.",
        )
        return redirect("client_detail", pk=client_id)
    messages.success(request, "Client deleted successfully")
    log_audit("client", "delete", client_id, client_str, request.user)
    return redirect("client_list")


# ===== LOADING MANAGEMENT =====


@login_required
def loading_list(request):
    loadings = Loading.objects.select_related("client")
    search = request.GET.get("search", "")
    if search:
        loadings = loadings.filter(
            Q(container_number__icontains=search)
            | Q(item_number__icontains=search)
            | Q(item_description__icontains=search)
            | Q(airline__icontains=search)
            | Q(cargo_type__icontains=search)
            | Q(client__name__icontains=search)
            | Q(origin__icontains=search)
            | Q(destination__icontains=search)
        )
    page_obj, query_string, page_range = paginate_queryset(request, loadings)
    return render(
        request,
        "logistics/loadings/list.html",
        {
            "loadings": page_obj,
            "search": search,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def loading_create(request):
    if request.method == "POST":
        form = LoadingForm(request.POST)
        if form.is_valid():
            loading = form.save(commit=False)
            loading.created_by = request.user
            loading.save()
            messages.success(request, "Cargo created successfully")
            log_audit("loading", "create", loading.id, str(loading), request.user)
            return redirect("loading_detail", pk=loading.id)
    else:
        form = LoadingForm()
    return render(
        request,
        "logistics/loadings/form.html",
        {"form": form, "title": "Create Loading"},
    )


@login_required
def loading_detail(request, pk):
    loading = get_object_or_404(Loading, pk=pk)
    transit = (
        Transit.objects.filter(container_number=loading.container_number)
        .order_by("-created_at")
        .first()
    )
    context = {
        "loading": loading,
        "transit": transit,
        "has_transit": transit is not None,
        "has_payment": hasattr(loading, "payment"),
    }
    return render(request, "logistics/loadings/detail.html", context)


@login_required
def loading_update(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("loading_list")
    loading = get_object_or_404(Loading, pk=pk)
    if request.method == "POST":
        form = LoadingForm(request.POST, instance=loading)
        if form.is_valid():
            form.save()
            messages.success(request, "Loading updated successfully")
            log_audit("loading", "update", loading.id, str(loading), request.user)
            return redirect("loading_detail", pk=loading.id)
    else:
        form = LoadingForm(instance=loading)
    return render(
        request,
        "logistics/loadings/form.html",
        {"form": form, "title": "Update Loading", "loading": loading},
    )


@login_required
def loading_delete(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("loading_list")
    loading = get_object_or_404(Loading, pk=pk)
    loading_str = str(loading)
    loading_id = loading.id
    loading.delete()
    messages.success(request, "Loading deleted successfully")
    log_audit("loading", "delete", loading_id, loading_str, request.user)
    return redirect("loading_list")


# ===== TRANSIT MANAGEMENT =====


@login_required
def transit_list(request):
    transits = Transit.objects.all()
    status = request.GET.get("status", "")
    if status:
        transits = transits.filter(status=status)
    page_obj, query_string, page_range = paginate_queryset(request, transits)
    return render(
        request,
        "logistics/transits/list.html",
        {
            "transits": page_obj,
            "status_filter": status,
            "status_choices": Transit.STATUS_CHOICES,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def transit_create(request):
    if request.method == "POST":
        form = TransitForm(request.POST)
        if form.is_valid():
            transit = form.save(commit=False)
            transit.created_by = request.user
            transit.save()
            messages.success(request, "Transit created successfully")
            log_audit("transit", "create", transit.id, str(transit), request.user)
            return redirect("transit_list")
    else:
        form = TransitForm()
        container_number = request.GET.get("container_number")
        if container_number:
            form.fields["container_number"].initial = container_number
    return render(
        request,
        "logistics/transits/form.html",
        {"form": form, "title": "Create Transit"},
    )


@login_required
def transit_update(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("transit_list")
    transit = get_object_or_404(Transit, pk=pk)
    if request.method == "POST":
        form = TransitForm(request.POST, instance=transit)
        if form.is_valid():
            form.save()
            messages.success(request, "Transit updated successfully")
            log_audit("transit", "update", transit.id, str(transit), request.user)
            return redirect("transit_list")
    else:
        form = TransitForm(instance=transit)
    return render(
        request,
        "logistics/transits/form.html",
        {"form": form, "title": "Update Transit"},
    )


# ===== PAYMENT MANAGEMENT =====


@login_required
def payment_list(request):
    payments = Payment.objects.select_related("loading__client")
    filter_type = request.GET.get("filter", "")
    if filter_type == "outstanding":
        payments = payments.filter(balance__gt=0)
    elif filter_type == "paid":
        payments = payments.filter(balance=0)
    page_obj, query_string, page_range = paginate_queryset(request, payments)
    totals = {
        "total_charged": Payment.objects.aggregate(Sum("amount_charged"))[
            "amount_charged__sum"
        ]
        or 0,
        "total_paid": Payment.objects.aggregate(Sum("amount_paid"))["amount_paid__sum"]
        or 0,
        "total_outstanding": Payment.objects.filter(balance__gt=0).aggregate(
            Sum("balance")
        )["balance__sum"]
        or 0,
    }
    can_view_financial_totals = _can_view_revenue(request.user)
    if not can_view_financial_totals:
        totals = {key: None for key in totals}
    context = {
        "payments": page_obj,
        "filter_type": filter_type,
        **totals,
        "can_view_financial_totals": can_view_financial_totals,
        "page_obj": page_obj,
        "query_string": query_string,
        "page_range": page_range,
    }
    return render(request, "logistics/payments/list.html", context)


@login_required
def payment_create(request, loading_id=None):
    if not has_app_permission(request.user, "create_invoices"):
        messages.error(request, "Permission denied")
        return redirect("payment_list")
    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.created_by = request.user
            payment.save()
            messages.success(request, "Invoice created successfully")
            log_audit("payment", "create", payment.id, str(payment), request.user)
            return redirect("payment_detail", pk=payment.id)
    else:
        form = PaymentForm()
        if loading_id:
            form.fields["loading"].initial = loading_id
    return render(
        request,
        "logistics/payments/form.html",
        {"form": form, "title": "Create Invoice", "payment": None},
    )


@login_required
def payment_update(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("payment_list")
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    if request.method == "POST":
        form = PaymentForm(request.POST, instance=payment)
        if form.is_valid():
            form.save()
            messages.success(request, "Invoice updated successfully")
            log_audit("payment", "update", payment.id, str(payment), request.user)
            return redirect("payment_detail", pk=payment.id)
    else:
        form = PaymentForm(instance=payment)
    return render(
        request,
        "logistics/payments/form.html",
        {"form": form, "title": "Update Invoice", "payment": payment},
    )


@login_required
def payment_delete(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("payment_list")

    if request.method != "POST":
        messages.error(request, "Invalid request method")
        return redirect("payment_detail", pk=pk)

    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )

    if (
        getattr(request.user, "role", None) == "managing_director"
        and (payment.amount_paid or 0) > 0
    ):
        messages.error(
            request, "Managing Director cannot delete paid or partially paid invoices."
        )
        return redirect("payment_detail", pk=pk)

    payment_str = str(payment)
    payment_id = payment.id

    payment.delete()
    messages.success(request, "Invoice deleted successfully")
    log_audit("payment", "delete", payment_id, payment_str, request.user)
    return redirect("payment_list")


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    transactions = payment.transactions.select_related(
        "created_by", "verified_by"
    ).all()
    transactions_active = transactions.filter(is_voided=False)
    transactions_voided = transactions.filter(is_voided=True)
    pending_totals = payment.transactions.filter(
        verification_status="pending", is_voided=False
    ).aggregate(total=Sum("amount"))
    pending_amount = pending_totals["total"] or 0
    pending_count = payment.transactions.filter(
        verification_status="pending", is_voided=False
    ).count()
    rejected_totals = payment.transactions.filter(
        verification_status="rejected", is_voided=False
    ).aggregate(total=Sum("amount"))
    rejected_amount = rejected_totals["total"] or 0
    rejected_count = payment.transactions.filter(
        verification_status="rejected", is_voided=False
    ).count()
    latest_wa_share = (
        AuditLog.objects.select_related("user")
        .filter(
            model_type="payment",
            action="update",
            object_id=payment.id,
            object_str__startswith="[WA]",
        )
        .order_by("-timestamp")
        .first()
    )
    if request.method == "POST":
        action = request.POST.get("action", "create_transaction")
        if action == "verify_transaction":
            if not has_app_permission(request.user, "approve_verify_receipts"):
                messages.error(request, "Permission denied")
                return redirect("payment_detail", pk=pk)
            transaction = get_object_or_404(
                payment.transactions.select_related("payment"),
                pk=request.POST.get("transaction_id"),
            )
            if getattr(transaction, "is_voided", False):
                messages.error(
                    request, "This receipt has been voided and cannot be verified."
                )
                return redirect("payment_detail", pk=pk)
            new_status = request.POST.get("verification_status", "pending")
            valid_statuses = {
                choice for choice, _ in PaymentTransaction.VERIFICATION_CHOICES
            }
            if new_status not in valid_statuses:
                messages.error(request, "Invalid verification status selected.")
                return redirect("payment_detail", pk=pk)
            notes = request.POST.get("verification_notes", "").strip()
            transaction.verification_status = new_status
            transaction.verification_notes = notes
            if new_status == "pending":
                transaction.verified_by = None
                transaction.verified_at = None
            else:
                transaction.verified_by = request.user
                transaction.verified_at = timezone.now()
            transaction.save()
            messages.success(
                request,
                f"Marked transaction {transaction.receipt_number} as {transaction.get_verification_status_display().lower()}.",
            )
            return redirect("payment_detail", pk=pk)
        elif action == "update_container_number":
            if not has_app_permission(request.user, "edit_delete_documents"):
                messages.error(request, "Permission denied")
                return redirect("payment_detail", pk=pk)
            loading = payment.loading
            if getattr(loading, "cargo_type", None) == "air_cargo":
                messages.error(
                    request, "Air cargo invoices do not use container numbers."
                )
                return redirect("payment_detail", pk=pk)
            container_number = (request.POST.get("container_number") or "").strip()
            if not container_number:
                messages.error(request, "Container number is required.")
                return redirect("payment_detail", pk=pk)
            loading.container_number = container_number
            loading.save(update_fields=["container_number", "updated_at"])
            log_audit(
                "payment",
                "update",
                payment.id,
                f"Updated invoice container number to {loading.container_number}",
                request.user,
            )
            messages.success(request, "Container number updated successfully.")
            return redirect("payment_detail", pk=pk)
        else:
            if not has_app_permission(request.user, "create_receipts"):
                messages.error(request, "Permission denied")
                return redirect("payment_detail", pk=pk)
            form = PaymentTransactionForm(request.POST)
            if form.is_valid():
                transaction = form.save(commit=False)
                transaction.payment = payment
                transaction.created_by = request.user
                transaction.save()
                log_audit(
                    "payment",
                    "update",
                    payment.id,
                    f"Payment transaction {transaction.receipt_number}",
                    request.user,
                )
                if transaction.verification_status == "approved":
                    messages.success(
                        request,
                        f"Recorded approved payment of ${transaction.amount:,.2f}.",
                    )
                elif transaction.verification_status == "rejected":
                    messages.warning(
                        request,
                        f"Recorded rejected receipt of ${transaction.amount:,.2f}.",
                    )
                else:
                    messages.success(
                        request,
                        f"Recorded receipt of ${transaction.amount:,.2f} (pending review). Invoice balance will update after approval.",
                    )
                return redirect("payment_detail", pk=pk)
    else:
        form = PaymentTransactionForm(
            initial={
                "payment_method": payment.payment_method or "cash",
                "payment_date": timezone.now(),
            }
        )
    context = {
        "payment": payment,
        "transactions": transactions,
        "transactions_active": transactions_active,
        "transactions_voided": transactions_voided,
        "transaction_form": form,
        "verification_choices": PaymentTransaction.VERIFICATION_CHOICES,
        "can_verify": has_app_permission(request.user, "approve_verify_receipts"),
        "can_void": has_app_permission(request.user, "void_unvoid_receipts"),
        "can_record_payment": has_app_permission(request.user, "create_receipts"),
        "can_update_container_number": has_app_permission(
            request.user, "edit_delete_documents"
        ),
        "can_delete_invoice": _has_full_app_access(request.user)
        and not (
            getattr(request.user, "role", None) == "managing_director"
            and (payment.amount_paid or 0) > 0
        ),
        "pending_amount": pending_amount,
        "pending_count": pending_count,
        "rejected_amount": rejected_amount,
        "rejected_count": rejected_count,
        "latest_wa_share": latest_wa_share,
    }
    return render(request, "logistics/payments/detail.html", context)


@login_required
def payment_invoice_whatsapp(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    loading = payment.loading
    client = loading.client

    invoice_preview_path = (
        reverse("payment_invoice", kwargs={"pk": payment.pk}) + "?preview=1"
    )
    invoice_full_url = request.build_absolute_uri(invoice_preview_path)
    is_air_cargo = getattr(loading, "cargo_type", None) == "air_cargo"
    invoice_label = "Air Cargo Invoice" if is_air_cargo else "Shipment Invoice"
    cargo_label = "Item" if is_air_cargo else "Container"
    cargo_value = loading.item_number if is_air_cargo else loading.container_number

    wa_message = (
        f"ROSHE LOGISTICS - {invoice_label} {payment.invoice_number}\n"
        f"Client: {client.name}\n"
        f"{cargo_label}: {cargo_value or '-'}\n"
        f"Amount Due: ${payment.balance:,.2f}\n"
        f"View Invoice: {invoice_full_url}"
    )

    target_phone = _normalize_whatsapp_phone(client.phone)

    if _is_whatsapp_api_mode_enabled():
        pdf_bytes = payment_invoice(request, pk).content
        sent = send_whatsapp_document(
            to_phone=target_phone,
            caption=f"{invoice_label} {payment.invoice_number}",
            filename=f"{(getattr(client, 'client_id', None) or 'NOCLIENT')}_INV_{payment.invoice_number}.pdf",
            file_bytes=pdf_bytes,
            mime_type="application/pdf",
        )
        if sent.ok:
            _log_whatsapp_share(
                model_type="payment",
                object_id=payment.id,
                label=f"Invoice {payment.invoice_number} [API:{sent.message_id or 'sent'}]",
                recipient_phone=target_phone,
                user=request.user,
            )
            messages.success(
                request, f"Invoice sent to WhatsApp ({target_phone or 'default'})."
            )
            return redirect("payment_detail", pk=payment.pk)

        messages.error(
            request,
            f"WhatsApp API send failed: {sent.error or 'unknown error'}. Opened link fallback.",
        )

    _log_whatsapp_share(
        model_type="payment",
        object_id=payment.id,
        label=f"Invoice {payment.invoice_number}",
        recipient_phone=target_phone,
        user=request.user,
    )
    return render(
        request,
        "logistics/whatsapp_launch.html",
        {
            "app_url": _whatsapp_app_url(phone=target_phone, message=wa_message),
            "web_url": _whatsapp_share_url(phone=target_phone, message=wa_message),
        },
    )


@login_required
def payment_receipt_whatsapp(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related("payment__loading__client"),
        pk=transaction_id,
    )

    payment = transaction.payment
    if getattr(transaction, "is_voided", False):
        messages.error(request, "This receipt has been voided.")
        return redirect("payment_detail", pk=payment.pk)
    if transaction.verification_status != "approved":
        messages.error(request, "This payment has not been verified yet.")
        return redirect("payment_detail", pk=payment.pk)

    loading = payment.loading
    client = loading.client

    receipt_preview_path = (
        reverse("payment_receipt", kwargs={"transaction_id": transaction.id})
        + "?preview=1"
    )
    receipt_full_url = request.build_absolute_uri(receipt_preview_path)

    wa_message = (
        f"ROSHE LOGISTICS - Receipt {transaction.receipt_number}\n"
        f"Client: {client.name}\n"
        f"Container: {loading.container_number}\n"
        f"Amount: ${transaction.amount:,.2f}\n"
        f"View Receipt: {receipt_full_url}"
    )

    target_phone = _normalize_whatsapp_phone(client.phone)

    if _is_whatsapp_api_mode_enabled():
        pdf_bytes = payment_receipt(request, transaction_id).content
        sent = send_whatsapp_document(
            to_phone=target_phone,
            caption=f"Payment Receipt {transaction.receipt_number}",
            filename=f"{(getattr(client, 'client_id', None) or 'NOCLIENT')}_RCT_{_numeric_part(transaction.receipt_number, default=f'{transaction.pk:05d}')}.pdf",
            file_bytes=pdf_bytes,
            mime_type="application/pdf",
        )
        if sent.ok:
            _log_whatsapp_share(
                model_type="receipt",
                object_id=transaction.id,
                label=f"Receipt {transaction.receipt_number} [API:{sent.message_id or 'sent'}]",
                recipient_phone=target_phone,
                user=request.user,
            )
            messages.success(
                request, f"Receipt sent to WhatsApp ({target_phone or 'default'})."
            )
            return redirect("payment_detail", pk=payment.pk)

        messages.error(
            request,
            f"WhatsApp API send failed: {sent.error or 'unknown error'}. Opened link fallback.",
        )

    _log_whatsapp_share(
        model_type="receipt",
        object_id=transaction.id,
        label=f"Receipt {transaction.receipt_number}",
        recipient_phone=target_phone,
        user=request.user,
    )
    return render(
        request,
        "logistics/whatsapp_launch.html",
        {
            "app_url": _whatsapp_app_url(phone=target_phone, message=wa_message),
            "web_url": _whatsapp_share_url(phone=target_phone, message=wa_message),
        },
    )


@csrf_exempt
def whatsapp_webhook(request):
    """Meta WhatsApp webhook (verification + status callbacks)."""
    verify_token = str(
        getattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "") or ""
    ).strip()

    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and verify_token and token == verify_token:
            return HttpResponse(challenge or "", status=200)
        return HttpResponse("Forbidden", status=403)

    if request.method != "POST":
        return HttpResponse("Method Not Allowed", status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    # Log raw status events for traceability.
    try:
        entries = payload.get("entry") or []
        for entry in entries:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                statuses = value.get("statuses") or []
                for status in statuses:
                    msg_id = status.get("id")
                    status_state = status.get("status")
                    recipient = status.get("recipient_id")
                    object_str = f"[WA_STATUS] id={msg_id or '-'} status={status_state or '-'} to={recipient or '-'}"
                    AuditLog.objects.create(
                        user=None,
                        model_type="payment",
                        action="update",
                        object_id=0,
                        object_str=object_str,
                    )
    except Exception:
        logger.exception("Failed to process WhatsApp webhook payload")

    return JsonResponse({"ok": True})


@login_required
def payment_invoice(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    preview_param = (request.GET.get("preview") or "").strip().lower()
    preview = preview_param in {"1", "true", "yes", "y"}
    buffer = BytesIO()
    loading = payment.loading
    client = loading.client
    is_air_cargo = getattr(loading, "cargo_type", None) == "air_cargo"

    issue_date = payment.created_at if payment.created_at else timezone.now()
    due_date = issue_date + timedelta(days=7)
    amount_due = payment.balance
    fee = (
        loading.handling_fees if is_air_cargo else payment.document_handling_fee
    ) or 0
    pvoc_fee = Decimal("0") if is_air_cargo else (payment.pvoc_fee or Decimal("0"))

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    table_text = normal.clone("InvoiceTableText")
    table_text.fontSize = 8.5
    table_text.leading = 10.5
    table_text.wordWrap = "CJK"

    table_number = table_text.clone("InvoiceTableNumber")
    table_number.alignment = TA_RIGHT

    def table_cell(value, style=table_text):
        return Paragraph(escape(str(value)), style)

    def table_markup(markup, style=table_text):
        return Paragraph(markup, style)

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        _draw_svg_logo_in_box(
            canvas_obj=canvas_obj, left=left, top=top, primary=primary
        )

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        # Shipment invoice label (yellow background, black text)
        label_text = (
            f"AIR CARGO INVOICE {payment.invoice_number}"
            if is_air_cargo
            else f"SHIPMENT INVOICE {payment.invoice_number}"
        )
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        # Accent separator line
        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_footer(canvas_obj, doc):
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        draw_footer(canvas_obj, doc)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=45,
        title=f"{'Air Cargo Invoice' if is_air_cargo else 'Shipment Invoice'} {payment.invoice_number}",
    )

    bill_to_lines = [
        "<b>BILL TO</b>",
        f"{client.name}",
        f"Phone: {client.phone}",
    ]
    if client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph("<br/>".join(bill_to_lines), normal)

    invoice_meta_lines = [
        f"<b>{'Air Cargo Invoice No' if is_air_cargo else 'Shipment Invoice No'}:</b> {payment.invoice_number}",
        f"<b>Invoice Date:</b> {issue_date.strftime('%Y-%m-%d')}",
        f"<b>Payment Due:</b> {due_date.strftime('%Y-%m-%d')}",
        f"<b>Amount Due (USD):</b> ${amount_due:,.2f}",
    ]
    invoice_meta = Paragraph("<br/>".join(invoice_meta_lines), normal)

    flow = getattr(loading, "flow_type", None)

    def display_date(value):
        return value.strftime("%Y-%m-%d") if value else ""

    if is_air_cargo:
        cargo_detail_rows = [
            ["AIR CARGO DETAILS", "", "", "", "", ""],
            [
                "Item Number",
                loading.item_number or "",
                "CTNs",
                loading.ctns if loading.ctns is not None else "",
                "Loading Date",
                display_date(loading.loading_date),
            ],
            [
                "Description",
                table_cell(loading.item_description or ""),
                "",
                "",
                "",
                "",
            ],
            [
                "Origin",
                loading.origin or "",
                "Destination",
                loading.destination or "",
                "Airline",
                loading.airline or "",
            ],
        ]
        cargo_detail_spans = [
            ("SPAN", (0, 0), (-1, 0)),
            ("SPAN", (1, 2), (-1, 2)),
        ]
        if loading.size_per_carton:
            size_row_index = len(cargo_detail_rows)
            cargo_detail_rows.append(
                ["Size per Carton", loading.size_per_carton, "", "", "", ""]
            )
            cargo_detail_spans.append(
                ("SPAN", (1, size_row_index), (-1, size_row_index))
            )
        cargo_detail_col_widths = [
            doc.width * 0.13,
            doc.width * 0.20,
            doc.width * 0.10,
            doc.width * 0.17,
            doc.width * 0.15,
            doc.width * 0.25,
        ]
        cargo_detail_label_columns = [0, 2, 4]
    else:
        cargo_detail_rows = [
            ["SHIPMENT DETAILS", "", "", ""],
            [
                "Route",
                f"{loading.origin or '—'} to {loading.destination or '—'}",
                "Flow",
                loading.get_flow_type_display() if flow else "—",
            ],
            [
                "Container Number",
                loading.container_number or "—",
                "Container Size",
                loading.get_container_size_display() if loading.container_size else "—",
            ],
            [
                "Loading Date",
                display_date(loading.loading_date),
                "CBM",
                (
                    f"{loading.weight:.2f}"
                    if flow == "lcl" and loading.weight is not None
                    else "—"
                ),
            ],
        ]
        cargo_detail_spans = [("SPAN", (0, 0), (-1, 0))]
        cargo_detail_col_widths = [
            doc.width * 0.16,
            doc.width * 0.34,
            doc.width * 0.16,
            doc.width * 0.34,
        ]
        cargo_detail_label_columns = [0, 2]

    cargo_detail_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#444444")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        *cargo_detail_spans,
    ]
    for label_column in cargo_detail_label_columns:
        cargo_detail_styles.extend(
            [
                (
                    "BACKGROUND",
                    (label_column, 1),
                    (label_column, -1),
                    colors.HexColor("#F7F7F7"),
                ),
                ("FONTNAME", (label_column, 1), (label_column, -1), "Helvetica-Bold"),
            ]
        )

    cargo_details_table = Table(
        cargo_detail_rows,
        colWidths=cargo_detail_col_widths,
        hAlign="LEFT",
    )
    cargo_details_table.setStyle(TableStyle(cargo_detail_styles))

    info_table = Table(
        [[bill_to, invoice_meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    if is_air_cargo:
        qty_label = (
            f"{loading.gross_weight:.2f}" if loading.gross_weight is not None else "—"
        )
        rate_label = (
            f"{loading.rate_per_kg:,.2f}" if loading.rate_per_kg is not None else "—"
        )
        freight_amount = (
            (loading.gross_weight * loading.rate_per_kg)
            if (loading.gross_weight is not None and loading.rate_per_kg is not None)
            else None
        )
    elif flow == "lcl":
        qty_label = f"{loading.weight:.2f}" if loading.weight is not None else "—"
        rate_label = (
            f"{payment.rate_per_cbm:,.2f}" if payment.rate_per_cbm is not None else "—"
        )
        freight_amount = (
            (loading.weight * payment.rate_per_cbm)
            if (loading.weight is not None and payment.rate_per_cbm is not None)
            else None
        )
    else:
        qty_label = "1"
        rate_label = (
            f"{payment.rate_per_container:,.2f}"
            if payment.rate_per_container is not None
            else "—"
        )
        freight_amount = (
            payment.rate_per_container
            if payment.rate_per_container is not None
            else None
        )

    freight_amount_label = (
        f"{freight_amount:,.2f}" if freight_amount is not None else "—"
    )

    route = f"{loading.origin or '—'} to {loading.destination or '—'}"
    if is_air_cargo:
        freight_item_cell = table_markup("<b>Air Cargo Freight Charges</b>")
        qty_header = "Gross Weight (KGS)"
        rate_header = "Rate (per kg)"
    else:
        freight_item_cell = table_cell(f"Shipment Charges ({route})")
        qty_header = "Quantity" if flow == "fcl" else "CBM"
        rate_header = "Rate"

    items = [
        ["Description", qty_header, rate_header, "Amount"],
        [
            freight_item_cell,
            table_cell(qty_label, table_number),
            table_cell(rate_label, table_number),
            table_cell(freight_amount_label, table_number),
        ],
    ]
    if fee and fee > 0:
        items.append(
            [
                table_cell(
                    "Handling Fees" if is_air_cargo else "Document & Handling Fees"
                ),
                "",
                "",
                table_cell(f"{fee:,.2f}", table_number),
            ]
        )
    if pvoc_fee and pvoc_fee > 0:
        pvoc_label = "PVOC"
        if flow == "lcl" and loading.weight is not None:
            per_cbm = pvoc_fee / loading.weight if loading.weight else pvoc_fee
            pvoc_label = f"PVOC ({loading.weight:.2f} CBM x {per_cbm:,.2f} / CBM)"
        elif flow == "fcl":
            pvoc_label = f"PVOC ({pvoc_fee:,.2f} / Container)"
        items.append(
            [
                table_cell(pvoc_label),
                "",
                "",
                table_cell(f"{pvoc_fee:,.2f}", table_number),
            ]
        )

    items_table = Table(
        items,
        colWidths=[
            doc.width * 0.46,
            doc.width * 0.18,
            doc.width * 0.18,
            doc.width * 0.18,
        ],
        hAlign="LEFT",
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    total_amount = payment.amount_charged
    totals_table = Table(
        [
            ["", "", "Total", f"{total_amount:,.2f}"],
            ["", "", "Amount Due (USD)", f"{amount_due:,.2f}"],
        ],
        colWidths=[
            doc.width * 0.46,
            doc.width * 0.18,
            doc.width * 0.18,
            doc.width * 0.18,
        ],
        hAlign="LEFT",
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEABOVE", (2, 0), (-1, 0), 0.7, colors.black),
                ("LINEBELOW", (2, -1), (-1, -1), 0.7, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph("<b>Notes / Terms</b>", heading),
        Paragraph(
            (
                "1. Air Cargo charges are payable before release unless otherwise agreed."
                if is_air_cargo
                else "1. Freight charges are to be paid when the container arrives at Mombasa port."
            ),
            small,
        ),
        Paragraph("2. A Surcharge of 5% will be charged on late payment", small),
        Paragraph(
            "3. Partial payments are recorded; outstanding balance must be cleared before release.",
            small,
        ),
        Paragraph("4. Thank you for choosing ROSHE LOGISTICS.", small),
        Spacer(1, 6),
        Paragraph("<b>Bank Details</b>", heading),
        Paragraph(
            "Bank details are available on request. Please contact ROSHE LOGISTICS.",
            small,
        ),
    ]

    story = [
        info_table,
        Spacer(1, 12),
        cargo_details_table,
        Spacer(1, 10),
        items_table,
        Spacer(1, 8),
        totals_table,
        Spacer(1, 14),
        *notes,
    ]

    # Header + branded footer on all pages
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_INV_{payment.invoice_number}.pdf"'
    )
    return response


@login_required
def payment_invoice_email(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("loading__client"), pk=pk
    )
    loading = payment.loading
    client = loading.client
    is_air_cargo = getattr(loading, "cargo_type", None) == "air_cargo"
    invoice_label = "Air Cargo Invoice" if is_air_cargo else "Shipment Invoice"
    cargo_label = "item" if is_air_cargo else "container"
    cargo_value = loading.item_number if is_air_cargo else loading.container_number

    default_to = client.email or ""
    default_subject = f"ROSHE LOGISTICS - {invoice_label} {payment.invoice_number}"
    default_message = (
        f"Dear {client.name},\n\n"
        f"Please find attached the {invoice_label.lower()} {payment.invoice_number} for {cargo_label} {cargo_value or '-'}.\n\n"
        "Regards,\nROSHE LOGISTICS"
    )

    if request.method == "POST":
        form = SendDocumentEmailForm(request.POST)
        if form.is_valid():
            try:
                pdf_bytes = payment_invoice(request, pk).content
                email = EmailMessage(
                    subject=form.cleaned_data["subject"],
                    body=form.cleaned_data["message"] or "",
                    to=[form.cleaned_data["to_email"]],
                )
                client_id = getattr(client, "client_id", None) or "NOCLIENT"
                email.attach(
                    filename=f"{client_id}_INV_{payment.invoice_number}.pdf",
                    content=pdf_bytes,
                    mimetype="application/pdf",
                )
                email.send(fail_silently=False)
            except Exception as exc:
                messages.error(request, f"Failed to send email: {exc}")
                return redirect("payment_detail", pk=payment.pk)

            messages.success(
                request,
                f"Invoice emailed to {form.cleaned_data['to_email']} (attached).",
            )
            return redirect("payment_detail", pk=payment.pk)
    else:
        form = SendDocumentEmailForm(
            initial={
                "to_email": default_to,
                "subject": default_subject,
                "message": default_message,
            }
        )

    return render(
        request,
        "logistics/documents/send_email.html",
        {
            "form": form,
            "doc_label": "Invoice",
            "doc_meta": f"Invoice {payment.invoice_number} · {cargo_label.title()} {cargo_value or '-'}",
            "back_url": reverse("payment_detail", kwargs={"pk": payment.pk}),
        },
    )


@login_required
def payment_receipt(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related(
            "payment__loading__client", "created_by", "verified_by"
        ),
        pk=transaction_id,
    )
    preview_param = (request.GET.get("preview") or "").strip().lower()
    preview = preview_param in {"1", "true", "yes", "y"}
    payment = transaction.payment
    if getattr(transaction, "is_voided", False):
        messages.error(request, "This receipt has been voided.")
        return redirect("payment_detail", pk=payment.pk)
    if transaction.verification_status != "approved":
        messages.error(request, "This payment has not been verified yet.")
        return redirect("payment_detail", pk=payment.pk)
    paid_up_to = (
        payment.transactions.filter(
            pk__lte=transaction.pk, verification_status="approved", is_voided=False
        ).aggregate(total=Sum("amount"))["total"]
        or transaction.amount
    )
    balance_after = payment.amount_charged - paid_up_to

    buffer = BytesIO()
    loading = payment.loading
    client = loading.client

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        _draw_svg_logo_in_box(
            canvas_obj=canvas_obj, left=left, top=top, primary=primary
        )

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        # Receipt label (yellow background, black text)
        label_text = f"PAYMENT RECEIPT {transaction.receipt_number}"
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_footer(canvas_obj, doc):
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        draw_footer(canvas_obj, doc)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=55,
        title=f"Payment Receipt {transaction.receipt_number}",
    )

    received_from = Paragraph(
        "<b>RECEIVED FROM</b><br/>" f"{client.name}<br/>" f"Phone: {client.phone}",
        normal,
    )

    payment_lines = [
        "<b>PAYMENT DETAILS</b>",
        f"Shipment Invoice No: {payment.invoice_number}",
        f"Container Number: {loading.container_number or '—'}",
        f"Payment Date: {transaction.payment_date.strftime('%Y-%m-%d %H:%M')}",
        f"Method: {transaction.get_payment_method_display()}",
    ]
    if transaction.reference:
        payment_lines.append(f"Reference: {transaction.reference}")
    payment_details = Paragraph("<br/>".join(payment_lines), normal)

    top_table = Table(
        [[received_from, payment_details]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    top_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    flow = getattr(loading, "flow_type", None)
    shipment_lines = [
        "<b>SHIPMENT</b>",
        f"Route: {loading.origin} to {loading.destination}",
        f"Loading Date: {loading.loading_date.strftime('%Y-%m-%d') if loading.loading_date else '—'}",
    ]
    if flow == "fcl":
        if loading.container_size:
            shipment_lines.append(
                f"Container Size: {loading.get_container_size_display()}"
            )
    else:
        cbm_value = f"{loading.weight:.2f} CBM" if loading.weight is not None else "—"
        shipment_lines.append(f"CBM: {cbm_value}")
    shipment_details = Paragraph("<br/>".join(shipment_lines), normal)

    summary_rows = [
        ["Summary", "Amount (USD)"],
        ["Amount Paid (this receipt)", f"{transaction.amount:,.2f}"],
        ["Paid Up To", f"{paid_up_to:,.2f}"],
        ["Outstanding After Payment", f"{balance_after:,.2f}"],
    ]
    summary_table = Table(
        summary_rows,
        colWidths=[doc.width * 0.65, doc.width * 0.35],
        hAlign="LEFT",
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    verification_note = "Verified"
    if transaction.verified_by:
        verification_note = (
            f"Verified by {transaction.verified_by.username} on "
            f"{transaction.verified_at.strftime('%Y-%m-%d %H:%M') if transaction.verified_at else '—'}"
        )

    audit = [
        Paragraph("<b>Notes</b>", heading),
        Paragraph(verification_note, small),
        Paragraph(
            f"Recorded by {transaction.created_by.username} on {transaction.created_at.strftime('%Y-%m-%d %H:%M')}",
            small,
        ),
    ]

    story = [
        top_table,
        Spacer(1, 12),
        shipment_details,
        Spacer(1, 10),
        summary_table,
        Spacer(1, 14),
        *audit,
    ]

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    receipt_digits = _numeric_part(
        transaction.receipt_number, default=f"{transaction.pk:05d}"
    )
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_RCT_{receipt_digits}.pdf"'
    )
    return response


@login_required
def payment_receipt_email(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related("payment__loading__client"),
        pk=transaction_id,
    )
    payment = transaction.payment
    loading = payment.loading
    client = loading.client

    if getattr(transaction, "is_voided", False):
        messages.error(request, "This receipt has been voided.")
        return redirect("payment_detail", pk=payment.pk)
    if transaction.verification_status != "approved":
        messages.error(request, "This payment has not been verified yet.")
        return redirect("payment_detail", pk=payment.pk)

    default_to = client.email or ""
    default_subject = f"ROSHE LOGISTICS - Receipt {transaction.receipt_number}"
    default_message = (
        f"Dear {client.name},\n\n"
        f"Please find attached the payment receipt {transaction.receipt_number} for container {loading.container_number}.\n\n"
        "Regards,\nROSHE LOGISTICS"
    )

    if request.method == "POST":
        form = SendDocumentEmailForm(request.POST)
        if form.is_valid():
            try:
                pdf_bytes = payment_receipt(request, transaction_id).content
                email = EmailMessage(
                    subject=form.cleaned_data["subject"],
                    body=form.cleaned_data["message"] or "",
                    to=[form.cleaned_data["to_email"]],
                )
                client_id = getattr(client, "client_id", None) or "NOCLIENT"
                receipt_digits = _numeric_part(
                    transaction.receipt_number, default=f"{transaction.pk:05d}"
                )
                email.attach(
                    filename=f"{client_id}_RCT_{receipt_digits}.pdf",
                    content=pdf_bytes,
                    mimetype="application/pdf",
                )
                email.send(fail_silently=False)
            except Exception as exc:
                messages.error(request, f"Failed to send email: {exc}")
                return redirect("payment_detail", pk=payment.pk)

            messages.success(
                request,
                f"Receipt emailed to {form.cleaned_data['to_email']} (attached).",
            )
            return redirect("payment_detail", pk=payment.pk)
    else:
        form = SendDocumentEmailForm(
            initial={
                "to_email": default_to,
                "subject": default_subject,
                "message": default_message,
            }
        )

    return render(
        request,
        "logistics/documents/send_email.html",
        {
            "form": form,
            "doc_label": "Receipt",
            "doc_meta": f"Receipt {transaction.receipt_number} · Container {loading.container_number}",
            "back_url": reverse("receipt_list"),
        },
    )


# ===== QUOTATIONS =====


@login_required
def quote_list(request):
    quotes = Quote.objects.select_related("client", "loading")
    page_obj, query_string, page_range = paginate_queryset(request, quotes)
    return render(
        request,
        "logistics/quotations/list.html",
        {
            "quotes": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def quote_create(request):
    if not has_app_permission(request.user, "create_quotations"):
        messages.error(request, "Permission denied")
        return redirect("quote_list")
    if request.method == "POST":
        form = QuoteForm(request.POST)
        if form.is_valid():
            quote = form.save(commit=False)
            quote.created_by = request.user
            quote.save()
            messages.success(request, "Quotation created successfully")
            log_audit("quote", "create", quote.id, str(quote), request.user)
            return redirect("quote_detail", quote_id=quote.id)
    else:
        form = QuoteForm()
    return render(
        request,
        "logistics/quotations/form.html",
        {"form": form, "title": "Create Quotation", "quote": None},
    )


@login_required
def quote_detail(request, quote_id):
    quote = get_object_or_404(
        Quote.objects.select_related("client", "loading"), pk=quote_id
    )
    flow = quote.flow_type
    is_air_cargo = quote.cargo_type == "air_cargo"
    fee = (
        quote.handling_fees if is_air_cargo else quote.document_handling_fee
    ) or Decimal("0")

    qty = None
    rate = None
    freight_amount = None
    unit_label = ""

    if is_air_cargo:
        qty = quote.gross_weight
        rate = quote.rate_per_kg
        unit_label = "KGS"
        if qty is not None and rate is not None:
            freight_amount = qty * rate
    elif flow == "lcl":
        qty = quote.cbm
        rate = quote.rate_per_cbm
        unit_label = "CBM"
        if qty is not None and rate is not None:
            freight_amount = qty * rate
    else:
        qty = Decimal("1")
        rate = quote.rate_per_container
        unit_label = "Container"
        if rate is not None:
            freight_amount = rate

    total = quote.amount_quoted
    pvoc_rate = Decimal("0") if is_air_cargo else (quote.pvoc_fee or Decimal("0"))
    pvoc_total = Decimal("0")
    if pvoc_rate and quote.flow_type == "lcl" and quote.cbm is not None:
        pvoc_total = quote.cbm * pvoc_rate
    elif pvoc_rate and quote.flow_type == "fcl":
        pvoc_total = pvoc_rate

    context = {
        "quote": quote,
        "breakdown": {
            "flow": flow,
            "qty": qty,
            "rate": rate,
            "unit_label": unit_label,
            "freight_amount": freight_amount,
            "fee": fee,
            "pvoc_rate": pvoc_rate,
            "pvoc_total": pvoc_total,
            "total": total,
            "cargo_type": quote.cargo_type,
        },
    }
    return render(request, "logistics/quotations/detail.html", context)


@login_required
def quote_pdf(request, quote_id):
    quote = get_object_or_404(Quote.objects.select_related("client"), pk=quote_id)
    client = quote.client
    client_id = getattr(client, "client_id", None) or "NOCLIENT"
    preview = request.GET.get("preview") == "1"
    quote_no = _quote_number(quote)

    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    styles = getSampleStyleSheet()
    normal = styles["BodyText"]
    normal.fontName = "Helvetica"
    normal.fontSize = 9
    normal.leading = 12

    heading = styles["Heading4"]
    heading.fontName = "Helvetica-Bold"
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles["BodyText"]
    small.fontName = "Helvetica"
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        logo_box = 44
        canvas_obj.setFillColor(primary)
        canvas_obj.rect(left, top - logo_box + 8, logo_box, logo_box, fill=1, stroke=0)

        logo_path = finders.find("images/roshe_logo.svg")
        if logo_path:
            try:
                from svglib.svglib import svg2rlg
                from reportlab.graphics import renderPDF

                drawing = svg2rlg(logo_path)
                desired_h = 34
                if drawing and drawing.height:
                    scale = desired_h / float(drawing.height)
                    drawing.scale(scale, scale)
                    renderPDF.draw(drawing, canvas_obj, left + 5, top - desired_h + 10)
            except Exception:
                pass

        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.drawString(
            company_x,
            top - 12,
            "Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202",
        )
        canvas_obj.drawString(
            company_x,
            top - 24,
            "+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com",
        )
        canvas_obj.drawString(company_x, top - 36, "www.roshegroup.com")

        label_text = (
            f"AIR CARGO QUOTATION {quote_no}"
            if quote.cargo_type == "air_cargo"
            else f"FREIGHT QUOTATION {quote_no}"
        )
        canvas_obj.setFont("Helvetica-Bold", 12)
        label_w = canvas_obj.stringWidth(label_text, "Helvetica-Bold", 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(
            label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0
        )
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(label_x + 8, label_y - 10, label_text)

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, top - 52, right, top - 52)

    def draw_page(canvas_obj, doc):
        draw_header(canvas_obj, doc)
        _draw_brand_footer(canvas_obj, doc, primary=primary, accent=accent)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=150,
        bottomMargin=55,
        title=f"{'Air Cargo' if quote.cargo_type == 'air_cargo' else 'Freight'} Quotation {quote_no}",
    )

    bill_to_lines = [
        "<b>BILL TO</b>",
        f"{client.name if client else '—'}",
        f"Client ID: {client_id}",
    ]
    if client and client.phone:
        bill_to_lines.append(f"Phone: {client.phone}")
    if client and client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client and client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph("<br/>".join(bill_to_lines), normal)

    meta_lines = [
        f"<b>Quotation No:</b> {quote_no}",
        f"<b>Status:</b> {quote.get_status_display()}",
        f"<b>Date:</b> {_fmt_dt(quote.created_at) or '—'}",
        f"<b>Cargo Type:</b> {quote.get_cargo_type_display()}",
        f"<b>Route:</b> {(quote.origin or '—')} to {(quote.destination or '—')}",
    ]
    if quote.cargo_type == "air_cargo":
        meta_lines.append(f"<b>Item Number:</b> {quote.item_number or '—'}")
        if quote.airline:
            meta_lines.append(f"<b>Airline:</b> {quote.airline}")
    meta = Paragraph("<br/>".join(meta_lines), normal)

    info_table = Table(
        [[bill_to, meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign="LEFT",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    is_air_cargo = quote.cargo_type == "air_cargo"
    fee = (
        quote.handling_fees if is_air_cargo else quote.document_handling_fee
    ) or Decimal("0")
    if is_air_cargo:
        qty_label = (
            _fmt_number(quote.gross_weight, decimals=2)
            if quote.gross_weight is not None
            else "—"
        )
        rate_label = (
            _fmt_number(quote.rate_per_kg, decimals=2)
            if quote.rate_per_kg is not None
            else "—"
        )
        freight_amount = (
            (quote.gross_weight * quote.rate_per_kg)
            if (quote.gross_weight is not None and quote.rate_per_kg is not None)
            else None
        )
        unit_label = "KGS"
    elif quote.flow_type == "lcl":
        qty_label = _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else "—"
        rate_label = (
            _fmt_number(quote.rate_per_cbm, decimals=2)
            if quote.rate_per_cbm is not None
            else "—"
        )
        freight_amount = (
            (quote.cbm * quote.rate_per_cbm)
            if (quote.cbm is not None and quote.rate_per_cbm is not None)
            else None
        )
        unit_label = "CBM"
    else:
        qty_label = "1"
        rate_label = (
            _fmt_number(quote.rate_per_container, decimals=2)
            if quote.rate_per_container is not None
            else "—"
        )
        freight_amount = (
            quote.rate_per_container if quote.rate_per_container is not None else None
        )
        unit_label = "Container"

    freight_amount_label = (
        _fmt_number(freight_amount, decimals=2) if freight_amount is not None else "—"
    )
    route = f"{quote.origin or '—'} to {quote.destination or '—'}"
    charge_label = "AIR CARGO" if is_air_cargo else "FREIGHT CHARGE"
    description_lines = [f"<b>{charge_label}</b>"]
    if quote.item_description:
        description_lines.append(
            f"Description of Items: {escape(quote.item_description)}"
        )
    freight_item = Paragraph("<br/>".join(description_lines), normal)

    if is_air_cargo:
        freight_basis = (
            f"{qty_label} KGS x {_fmt_number(quote.rate_per_kg, decimals=2)} / KG"
            if quote.rate_per_kg is not None
            else "Per KG"
        )
    elif quote.flow_type == "lcl":
        freight_basis = (
            f"{qty_label} CBM x {_fmt_number(quote.rate_per_cbm, decimals=2)} / CBM"
            if quote.rate_per_cbm is not None
            else "Per CBM"
        )
    else:
        freight_basis = (
            f"{_fmt_number(quote.rate_per_container, decimals=2)} / Container"
            if quote.rate_per_container is not None
            else "Per Container"
        )

    items = [["NO.", "DETAILS", "RATE BASIS", "TOTAL"]]
    charge_rows = [[freight_item, freight_basis, freight_amount_label]]
    if fee and fee > 0:
        fee_label = "HANDLING FEES" if is_air_cargo else "DOCUMENTS FEE"
        charge_rows.append([fee_label, "Flat charge", _fmt_number(fee, decimals=2)])
    pvoc_rate = Decimal("0") if is_air_cargo else (quote.pvoc_fee or Decimal("0"))
    pvoc_total = Decimal("0")
    if pvoc_rate and quote.flow_type == "lcl" and quote.cbm is not None:
        pvoc_total = quote.cbm * pvoc_rate
    elif pvoc_rate and quote.flow_type == "fcl":
        pvoc_total = pvoc_rate
    if pvoc_total and pvoc_total > 0:
        pvoc_label = "PVOC"
        pvoc_basis = "Per container"
        if quote.flow_type == "lcl" and quote.cbm is not None:
            pvoc_basis = f"{_fmt_number(quote.cbm, decimals=2)} CBM x {_fmt_number(pvoc_rate, decimals=2)} / CBM"
        elif quote.flow_type == "fcl":
            pvoc_basis = f"{_fmt_number(pvoc_rate, decimals=2)} / Container"
        charge_rows.append(
            [pvoc_label, pvoc_basis, _fmt_number(pvoc_total, decimals=2)]
        )

    for index, (detail, basis, amount) in enumerate(charge_rows, start=1):
        items.append([str(index), detail, basis, amount])

    items_table = Table(
        items,
        colWidths=[
            doc.width * 0.16,
            doc.width * 0.46,
            doc.width * 0.22,
            doc.width * 0.16,
        ],
        hAlign="LEFT",
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    totals_table = Table(
        [
            [
                "Grand Total (USD)",
                "",
                "",
                _fmt_number(quote.amount_quoted, decimals=2),
            ],
        ],
        colWidths=[
            doc.width * 0.16,
            doc.width * 0.46,
            doc.width * 0.22,
            doc.width * 0.16,
        ],
        hAlign="LEFT",
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (2, 0)),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (2, 0), "RIGHT"),
                ("ALIGN", (3, 0), (3, 0), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph("<b>Notes / Terms</b>", heading),
        Paragraph("1. Quotation valid for 7 days from date of issue.", small),
        Paragraph("2. Prices may change due to carrier / customs adjustments.", small),
        Paragraph("3. Thank you for choosing ROSHE LOGISTICS.", small),
    ]

    story = [
        info_table,
        Spacer(1, 12),
        items_table,
        Spacer(1, 8),
        totals_table,
        Spacer(1, 14),
        *notes,
    ]

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    disposition = "inline" if preview else "attachment"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{client_id}_QTN_{quote.pk:05d}.pdf"'
    )
    return response


@login_required
def quote_update(request, quote_id):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("quote_list")
    quote = get_object_or_404(
        Quote.objects.select_related("client", "loading"), pk=quote_id
    )
    if request.method == "POST":
        form = QuoteForm(request.POST, instance=quote)
        if form.is_valid():
            form.save()
            messages.success(request, "Quotation updated successfully")
            log_audit("quote", "update", quote.id, str(quote), request.user)
            return redirect("quote_detail", quote_id=quote.id)
    else:
        form = QuoteForm(instance=quote)
    return render(
        request,
        "logistics/quotations/form.html",
        {"form": form, "title": "Update Quotation", "quote": quote},
    )


@login_required
def quote_delete(request, quote_id):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("quote_list")
    quote = get_object_or_404(Quote, pk=quote_id)
    quote_str = str(quote)
    quote_pk = quote.pk
    quote.delete()
    messages.success(request, "Quotation deleted successfully")
    log_audit("quote", "delete", quote_pk, quote_str, request.user)
    return redirect("quote_list")


@login_required
def quote_convert_to_invoice(request, quote_id):
    if request.method != "POST":
        return redirect("quote_detail", quote_id=quote_id)

    quote = get_object_or_404(
        Quote.objects.select_related("client", "loading"), pk=quote_id
    )

    if quote.status != "accepted":
        messages.error(
            request,
            "This quotation must be marked as Accepted before converting to an invoice.",
        )
        return redirect("quote_detail", quote_id=quote_id)

    loading = quote.loading
    if loading is None:
        missing = []
        if not quote.loading_date:
            missing.append("Loading date")
        if not (quote.origin or "").strip():
            missing.append("Origin")
        if not (quote.destination or "").strip():
            missing.append("Destination")

        container_number = quote.container_number
        if not (container_number or "").strip():
            if quote.cargo_type == "air_cargo":
                container_number = ""
            elif quote.flow_type == "lcl":
                container_number = f"LCL-{quote.pk:05d}"
            else:
                container_number = f"FCL-{quote.pk:05d}"

        if quote.cargo_type == "air_cargo":
            if not (quote.item_number or "").strip():
                missing.append("Item number")
            if not (quote.item_description or "").strip():
                missing.append("Description")
            if quote.ctns is None:
                missing.append("CTNs")
            if quote.gross_weight is None:
                missing.append("Gross weight")
            if quote.rate_per_kg is None:
                missing.append("Rate per kg")

        if missing:
            messages.error(
                request,
                "Cannot convert to invoice. Please fill: " + ", ".join(missing) + ".",
            )
            return redirect("quote_detail", quote_id=quote_id)

        container_size = quote.container_size
        if container_size is None:
            # Loading.container_size is NOT NULL in DB; use blank string or LCL size.
            container_size = "lcl" if quote.flow_type == "lcl" else ""

        loading = Loading.objects.create(
            flow_type=quote.flow_type,
            cargo_type=quote.cargo_type,
            client=quote.client,
            loading_date=quote.loading_date,
            item_number=quote.item_number,
            item_description=quote.item_description,
            ctns=quote.ctns,
            weight=quote.cbm,
            gross_weight=quote.gross_weight,
            rate_per_kg=quote.rate_per_kg,
            handling_fees=quote.handling_fees or 0,
            airline=quote.airline,
            size_per_carton=quote.size_per_carton,
            container_number=container_number,
            container_size=container_size,
            origin=(quote.origin or "").strip(),
            destination=(quote.destination or "").strip(),
            created_by=request.user,
        )
        quote.loading = loading

    existing_payment = getattr(loading, "payment", None)
    if existing_payment:
        quote.status = "converted"
        quote.save(update_fields=["status", "loading", "updated_at"])
        messages.info(
            request,
            "An invoice already exists for this cargo. Opened the existing invoice.",
        )
        return redirect("payment_detail", pk=existing_payment.pk)

    payment = Payment.objects.create(
        loading=loading,
        rate_per_cbm=quote.rate_per_cbm,
        rate_per_container=quote.rate_per_container,
        document_handling_fee=quote.document_handling_fee or 0,
        pvoc_fee=(
            (quote.cbm * quote.pvoc_fee)
            if quote.flow_type == "lcl" and quote.cbm is not None and quote.pvoc_fee
            else (quote.pvoc_fee or 0)
        ),
        amount_charged=0,
        amount_paid=0,
        balance=0,
        created_by=request.user,
    )
    quote.status = "converted"
    quote.save(update_fields=["status", "loading", "updated_at"])

    log_audit(
        "quote", "update", quote.id, f"{quote} converted to invoice", request.user
    )
    log_audit("payment", "create", payment.id, str(payment), request.user)
    messages.success(request, "Quotation converted to invoice successfully")
    return redirect("payment_detail", pk=payment.pk)


# ===== RECEIPTS =====


@login_required
def receipt_list(request):
    receipts = PaymentTransaction.objects.select_related(
        "payment__loading__client", "created_by", "verified_by"
    )
    search = (request.GET.get("search") or "").strip()
    show_voided_param = (request.GET.get("show_voided") or "").strip().lower()
    show_voided = show_voided_param in {"1", "true", "yes", "y", "on"}

    if not show_voided:
        receipts = receipts.filter(is_voided=False)

    if search:
        search_filters = (
            Q(reference__icontains=search)
            | Q(payment__loading__container_number__icontains=search)
            | Q(payment__loading__client__name__icontains=search)
            | Q(payment__loading__client__client_id__icontains=search)
        )

        receipt_id_text = _numeric_part(search)
        if receipt_id_text and receipt_id_text.isdigit():
            search_filters |= Q(pk=int(receipt_id_text))

        receipts = receipts.filter(search_filters)

    receipts = receipts.order_by("-created_at", "-pk")
    page_obj, query_string, page_range = paginate_queryset(request, receipts)
    return render(
        request,
        "logistics/receipts/list.html",
        {
            "receipts": page_obj,
            "search": search,
            "show_voided": show_voided,
            "can_void": has_app_permission(request.user, "void_unvoid_receipts"),
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def receipt_void(request, transaction_id):
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("receipt_list")

    if not has_app_permission(request.user, "void_unvoid_receipts"):
        messages.error(request, "Permission denied")
        return redirect("receipt_list")

    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related("payment"),
        pk=transaction_id,
    )

    if transaction.is_voided:
        messages.info(request, "This receipt is already voided.")
        return redirect("payment_detail", pk=transaction.payment_id)

    reason = (request.POST.get("void_reason") or "").strip()
    if not reason:
        messages.error(request, "Please provide a reason for voiding this receipt.")
        return redirect("payment_detail", pk=transaction.payment_id)

    transaction.is_voided = True
    transaction.void_reason = reason
    transaction.voided_by = request.user
    transaction.voided_at = timezone.now()
    transaction.save(
        update_fields=[
            "is_voided",
            "void_reason",
            "voided_by",
            "voided_at",
            "updated_at",
        ]
    )

    log_audit(
        "receipt",
        "void",
        transaction.id,
        f"Receipt {transaction.receipt_number or transaction.id} voided: {reason}",
        request.user,
    )
    messages.success(request, "Receipt voided successfully.")
    return redirect("payment_detail", pk=transaction.payment_id)


@login_required
def receipt_unvoid(request, transaction_id):
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("receipt_list")

    if not has_app_permission(request.user, "void_unvoid_receipts"):
        messages.error(request, "Permission denied")
        return redirect("receipt_list")

    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related("payment"),
        pk=transaction_id,
    )

    if not transaction.is_voided:
        messages.info(request, "This receipt is not voided.")
        return redirect("payment_detail", pk=transaction.payment_id)

    previous_reason = transaction.void_reason
    transaction.is_voided = False
    transaction.void_reason = ""
    transaction.voided_by = None
    transaction.voided_at = None
    transaction.save(
        update_fields=[
            "is_voided",
            "void_reason",
            "voided_by",
            "voided_at",
            "updated_at",
        ]
    )

    log_audit(
        "receipt",
        "unvoid",
        transaction.id,
        f'Receipt {transaction.receipt_number or transaction.id} unvoided (previous reason: {previous_reason or "-"}).',
        request.user,
    )
    messages.success(request, "Receipt unvoided successfully.")
    return redirect("payment_detail", pk=transaction.payment_id)


# ===== CONTAINER RETURNS =====


@login_required
def container_return_list(request):
    containers = ContainerReturn.objects.select_related("loading")
    status = request.GET.get("status", "")
    if status:
        containers = containers.filter(status=status)
    page_obj, query_string, page_range = paginate_queryset(request, containers)
    return render(
        request,
        "logistics/containers/list.html",
        {
            "containers": page_obj,
            "status_filter": status,
            "status_choices": ContainerReturn.STATUS_CHOICES,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
        },
    )


@login_required
def container_return_create(request):
    if request.method == "POST":
        form = ContainerReturnForm(request.POST)
        if form.is_valid():
            container = form.save(commit=False)
            container.created_by = request.user
            container.save()
            messages.success(request, "Container return recorded")
            log_audit(
                "container_return", "create", container.id, str(container), request.user
            )
            return redirect("container_return_list")
    else:
        form = ContainerReturnForm()
    return render(
        request,
        "logistics/containers/form.html",
        {"form": form, "title": "Record Container Return"},
    )


@login_required
def container_return_update(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("container_return_list")
    container = get_object_or_404(ContainerReturn, pk=pk)
    if request.method == "POST":
        form = ContainerReturnForm(request.POST, instance=container)
        if form.is_valid():
            form.save()
            messages.success(request, "Container return updated successfully")
            log_audit(
                "container_return", "update", container.id, str(container), request.user
            )
            return redirect("container_return_list")
    else:
        form = ContainerReturnForm(instance=container)
    return render(
        request,
        "logistics/containers/form.html",
        {"form": form, "title": "Update Container Return"},
    )


# ===== REPORTS & EXPORTS =====


def _pdf_report_response(filename, title, headers, rows):
    """Render tabular data into a downloadable PDF report."""
    normalized_rows = [
        [str(value) if value is not None else "" for value in row]
        for row in (rows or [["" for _ in headers]])
    ]
    buffer = BytesIO()
    page_size = landscape(A4)
    primary = colors.HexColor("#003366")
    accent = colors.HexColor("#f2cb3f")

    generated_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=24,
        rightMargin=24,
        topMargin=62,
        bottomMargin=46,
    )

    def draw_page(canvas_obj, doc_obj):
        width, height = doc_obj.pagesize
        left = doc_obj.leftMargin
        right = width - doc_obj.rightMargin

        # Header baseline (keep consistent across pages)
        top = height - doc_obj.topMargin + 42

        _draw_svg_logo_in_box(
            canvas_obj=canvas_obj, left=left, top=top, primary=primary
        )

        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 11)
        canvas_obj.drawString(company_x, top, "ROSHE LOGISTICS")
        canvas_obj.setFont("Helvetica", 8.5)
        canvas_obj.drawString(company_x, top - 12, title)
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(colors.grey)
        canvas_obj.drawRightString(right, top - 12, f"Generated: {generated_at}")

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(1.5)
        canvas_obj.line(left, top - 22, right, top - 22)

        _draw_brand_footer(canvas_obj, doc_obj, primary=primary, accent=accent)

    styles = getSampleStyleSheet()

    title_style = styles["Heading1"].clone("report_title_stub")
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 1  # canvas draws the actual title
    title_style.leading = 1

    cell_style = styles["BodyText"].clone("report_cell")
    cell_style.fontName = "Helvetica"
    cell_style.fontSize = 8.5
    cell_style.leading = 10
    cell_style.textColor = colors.black

    header_style = styles["BodyText"].clone("report_header")
    header_style.fontName = "Helvetica-Bold"
    header_style.fontSize = 9
    header_style.leading = 11
    header_style.textColor = colors.white

    def as_para(text, style):
        # Keep it simple and safe; ReportLab Paragraph handles basic wrapping.
        return Paragraph(str(text or "").replace("\n", "<br/>"), style)

    data = [[as_para(h, header_style) for h in headers]]
    for row in normalized_rows:
        data.append([as_para(v, cell_style) for v in row])

    # Column sizing: weight by observed content length (bounded) to avoid ugly equal-width tables.
    sample = normalized_rows[:50]
    lengths = []
    for col_idx, header in enumerate(headers):
        max_len = len(str(header))
        for r in sample:
            if col_idx < len(r):
                max_len = max(max_len, len(str(r[col_idx] or "")))
        lengths.append(max(6, min(max_len, 40)))
    total = sum(lengths) or 1
    col_widths = [max(0.75 * inch, doc.width * (l / total)) for l in lengths]
    # Adjust if rounding pushes beyond available width.
    width_sum = sum(col_widths)
    if width_sum > doc.width:
        scale = doc.width / width_sum
        col_widths = [w * scale for w in col_widths]

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")

    numeric_keywords = (
        "amount",
        "balance",
        "rate",
        "cbm",
        "weight",
        "ctns",
        "fees",
        "total",
    )
    numeric_cols = [
        idx
        for idx, h in enumerate(headers)
        if any(k in str(h).strip().lower() for k in numeric_keywords)
    ]

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), primary),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
            ]
        )
    )

    for col_idx in numeric_cols:
        table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (col_idx, 1), (col_idx, -1), "RIGHT"),
                ]
            )
        )

    story = [Paragraph(title, title_style), Spacer(1, 6)]
    story.append(table)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def reports_dashboard(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    totals = {
        # "Revenue" here means what was invoiced/charged.
        "total_revenue": Payment.objects.aggregate(Sum("amount_charged"))[
            "amount_charged__sum"
        ]
        or 0,
        # "Income" means money actually received (approved, non-voided receipts).
        "income_revenue": PaymentTransaction.objects.filter(
            verification_status="approved",
            is_voided=False,
        ).aggregate(Sum("amount"))["amount__sum"]
        or 0,
        # Kept for backward compatibility; amount_paid is derived from approved receipts.
        "total_paid": Payment.objects.aggregate(Sum("amount_paid"))["amount_paid__sum"]
        or 0,
        "outstanding_balance": Payment.objects.filter(balance__gt=0).aggregate(
            Sum("balance")
        )["balance__sum"]
        or 0,
    }
    can_view_financial_totals = _can_view_revenue(request.user)
    if not can_view_financial_totals:
        totals = {key: None for key in totals}
    context = {
        "total_clients": Client.objects.count(),
        "total_loadings": Loading.objects.count(),
        "in_transit_count": Transit.objects.filter(status="in_transit").count(),
        **totals,
        "can_view_financial_totals": can_view_financial_totals,
    }
    return render(request, "logistics/reports/dashboard.html", context)


@login_required
def export_clients_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="clients_report_{report_date}.csv"'
    )
    # Excel-friendly UTF-8 BOM
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Client ID",
            "Name",
            "Contact Person",
            "Phone",
            "Address",
            "Date Registered",
            "Remarks",
        ]
    )
    for client in Client.objects.all().order_by("client_id"):
        writer.writerow(
            [
                client.client_id,
                client.name,
                client.contact_person,
                client.phone,
                client.address,
                _fmt_dt(client.date_registered),
                client.remarks or "",
            ]
        )
    log_audit("client", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_clients_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Client ID",
        "Name",
        "Contact Person",
        "Phone",
        "Address",
        "Date Registered",
        "Remarks",
    ]
    rows = [
        [
            client.client_id,
            client.name,
            client.contact_person,
            client.phone,
            client.address,
            _fmt_dt(client.date_registered),
            client.remarks or "",
        ]
        for client in Client.objects.all().order_by("client_id")
    ]
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"clients_report_{report_date}.pdf", "Clients Report", headers, rows
    )
    log_audit("client", "export", 0, "PDF Export", request.user)
    return response


@login_required
def export_shipments_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="shipments_report_{report_date}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Flow Type",
            "Cargo Type",
            "Client",
            "Loading Date",
            "Item Number",
            "Item Description",
            "CTNs",
            "Gross Weight",
            "Rate per Kg",
            "Handling Fees",
            "Air Cargo Total",
            "Airline",
            "Size per Carton",
            "CBM",
            "Container Number",
            "Container Size",
            "Origin",
            "Destination",
        ]
    )
    for loading in Loading.objects.select_related("client").order_by(
        "-loading_date", "-id"
    ):
        writer.writerow(
            [
                loading.get_flow_type_display(),
                loading.get_cargo_type_display(),
                loading.client.name,
                _fmt_dt(loading.loading_date),
                loading.item_number or "",
                loading.item_description or "",
                loading.ctns or "",
                (
                    _fmt_number(loading.gross_weight, decimals=2)
                    if loading.cargo_type == "air_cargo"
                    and loading.gross_weight is not None
                    else ""
                ),
                (
                    _fmt_number(loading.rate_per_kg, decimals=2)
                    if loading.rate_per_kg is not None
                    else ""
                ),
                _fmt_number(loading.handling_fees, decimals=2),
                (
                    _fmt_number(loading.air_cargo_total, decimals=2)
                    if loading.air_cargo_total is not None
                    else ""
                ),
                loading.airline or "",
                loading.size_per_carton or "",
                (
                    _fmt_number(loading.weight, decimals=2)
                    if loading.cargo_type != "air_cargo" and loading.weight is not None
                    else ""
                ),
                loading.container_number,
                loading.get_container_size_display() if loading.container_size else "",
                loading.origin,
                loading.destination,
            ]
        )
    log_audit("loading", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_shipments_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Flow Type",
        "Cargo Type",
        "Client",
        "Loading Date",
        "Item Number",
        "Item Description",
        "CTNs",
        "Gross Weight",
        "Rate per Kg",
        "Handling Fees",
        "Air Cargo Total",
        "Airline",
        "Size per Carton",
        "CBM",
        "Container Number",
        "Container Size",
        "Origin",
        "Destination",
    ]
    rows = [
        [
            loading.get_flow_type_display(),
            loading.get_cargo_type_display(),
            loading.client.name,
            _fmt_dt(loading.loading_date),
            loading.item_number or "",
            loading.item_description or "",
            loading.ctns or "",
            (
                _fmt_number(loading.gross_weight, decimals=2)
                if loading.cargo_type == "air_cargo"
                and loading.gross_weight is not None
                else ""
            ),
            _fmt_money(loading.rate_per_kg),
            _fmt_money(loading.handling_fees),
            _fmt_money(loading.air_cargo_total),
            loading.airline or "",
            loading.size_per_carton or "",
            (
                _fmt_number(loading.weight, decimals=2)
                if loading.cargo_type != "air_cargo" and loading.weight is not None
                else ""
            ),
            loading.container_number,
            loading.get_container_size_display() if loading.container_size else "",
            loading.origin,
            loading.destination,
        ]
        for loading in Loading.objects.select_related("client").order_by(
            "-loading_date", "-id"
        )
    ]
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"shipments_report_{report_date}.pdf", "Shipments Report", headers, rows
    )
    log_audit("loading", "export", 0, "PDF Export", request.user)
    return response


@login_required
def export_payments_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="payments_report_{report_date}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Container Number",
            "Flow Type",
            "Client",
            "Rate per CBM",
            "Rate per Container",
            "Amount Charged",
            "Amount Paid",
            "Balance",
            "Payment Date",
            "Payment Method",
            "Receipt Number",
        ]
    )
    for payment in Payment.objects.select_related("loading__client").order_by("-id"):
        writer.writerow(
            [
                payment.loading.container_number,
                payment.loading.get_flow_type_display(),
                payment.loading.client.name,
                (
                    _fmt_number(payment.rate_per_cbm, decimals=2)
                    if payment.rate_per_cbm is not None
                    else ""
                ),
                (
                    _fmt_number(payment.rate_per_container, decimals=2)
                    if payment.rate_per_container is not None
                    else ""
                ),
                _fmt_number(payment.amount_charged, decimals=2),
                _fmt_number(payment.amount_paid, decimals=2),
                _fmt_number(payment.balance, decimals=2),
                _fmt_dt(payment.payment_date),
                payment.get_payment_method_display() if payment.payment_method else "",
                payment.receipt_number or "",
            ]
        )
    log_audit("payment", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_payments_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Container Number",
        "Flow Type",
        "Client",
        "Rate per CBM",
        "Rate per Container",
        "Amount Charged",
        "Amount Paid",
        "Balance",
        "Payment Date",
        "Payment Method",
        "Receipt Number",
    ]
    rows = [
        [
            payment.loading.container_number,
            payment.loading.get_flow_type_display(),
            payment.loading.client.name,
            f"${payment.rate_per_cbm:,.2f}" if payment.rate_per_cbm is not None else "",
            (
                f"${payment.rate_per_container:,.2f}"
                if payment.rate_per_container is not None
                else ""
            ),
            f"${payment.amount_charged:,.2f}",
            f"${payment.amount_paid:,.2f}",
            f"${payment.balance:,.2f}",
            (
                payment.payment_date.strftime("%Y-%m-%d %H:%M")
                if payment.payment_date
                else ""
            ),
            payment.get_payment_method_display() if payment.payment_method else "",
            payment.receipt_number or "",
        ]
        for payment in Payment.objects.select_related("loading__client")
    ]
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"payments_report_{report_date}.pdf", "Payments Report", headers, rows
    )
    log_audit("payment", "export", 0, "PDF Export", request.user)
    return response


@login_required
def export_receipts_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="receipts_report_{report_date}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Receipt Number",
            "Verification Status",
            "Is Voided",
            "Amount",
            "Payment Date",
            "Payment Method",
            "Reference",
            "Invoice Number",
            "Container Number",
            "Flow Type",
            "Client",
            "Created By",
            "Verified By",
            "Verified At",
            "Voided By",
            "Voided At",
            "Void Reason",
        ]
    )

    receipts = PaymentTransaction.objects.select_related(
        "payment__loading__client",
        "created_by",
        "verified_by",
        "voided_by",
    ).order_by("-payment_date", "-id")
    for receipt in receipts:
        loading = receipt.payment.loading
        writer.writerow(
            [
                receipt.receipt_number,
                receipt.get_verification_status_display(),
                "Yes" if receipt.is_voided else "No",
                _fmt_number(receipt.amount, decimals=2),
                _fmt_dt(receipt.payment_date),
                receipt.get_payment_method_display() if receipt.payment_method else "",
                receipt.reference or "",
                receipt.payment.invoice_number,
                loading.container_number,
                loading.get_flow_type_display(),
                loading.client.name,
                str(receipt.created_by) if receipt.created_by else "",
                str(receipt.verified_by) if receipt.verified_by else "",
                _fmt_dt(receipt.verified_at),
                str(receipt.voided_by) if receipt.voided_by else "",
                _fmt_dt(receipt.voided_at),
                receipt.void_reason or "",
            ]
        )

    log_audit("receipt", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_receipts_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Receipt Number",
        "Status",
        "Voided",
        "Amount",
        "Payment Date",
        "Method",
        "Invoice",
        "Container",
        "Client",
    ]
    rows = []
    receipts = PaymentTransaction.objects.select_related(
        "payment__loading__client"
    ).order_by("-payment_date", "-id")
    for receipt in receipts:
        loading = receipt.payment.loading
        rows.append(
            [
                receipt.receipt_number,
                receipt.get_verification_status_display(),
                "Yes" if receipt.is_voided else "No",
                f"${receipt.amount:,.2f}",
                (
                    receipt.payment_date.strftime("%Y-%m-%d %H:%M")
                    if receipt.payment_date
                    else ""
                ),
                receipt.get_payment_method_display() if receipt.payment_method else "",
                receipt.payment.invoice_number,
                loading.container_number,
                loading.client.name,
            ]
        )

    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"receipts_report_{report_date}.pdf", "Receipts Report", headers, rows
    )
    log_audit("receipt", "export", 0, "PDF Export", request.user)
    return response


@login_required
def export_containers_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="container_returns_report_{report_date}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Container Number",
            "Container Size",
            "Cargo Container",
            "Client",
            "Return Date",
            "Condition",
            "Status",
            "Remarks",
        ]
    )
    for container in ContainerReturn.objects.select_related("loading__client").order_by(
        "-return_date", "-id"
    ):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (
                container.loading.get_container_size_display()
                if container.loading.container_size
                else ""
            )
        )
        writer.writerow(
            [
                container.container_number,
                size_display,
                container.loading.container_number,
                container.loading.client.name,
                _fmt_dt(container.return_date),
                container.get_condition_display(),
                container.get_status_display(),
                container.remarks or "",
            ]
        )
    log_audit("container_return", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_containers_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Container Number",
        "Container Size",
        "Cargo Container",
        "Client",
        "Return Date",
        "Condition",
        "Status",
        "Remarks",
    ]
    rows = []
    for container in ContainerReturn.objects.select_related("loading__client").order_by(
        "-return_date", "-id"
    ):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (
                container.loading.get_container_size_display()
                if container.loading.container_size
                else ""
            )
        )
        rows.append(
            [
                container.container_number,
                size_display,
                container.loading.container_number,
                container.loading.client.name,
                _fmt_dt(container.return_date),
                container.get_condition_display(),
                container.get_status_display(),
                container.remarks or "",
            ]
        )
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"container_returns_report_{report_date}.pdf",
        "Container Returns Report",
        headers,
        rows,
    )
    log_audit("container_return", "export", 0, "PDF Export", request.user)
    return response


@login_required
def export_quotes_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="quotations_report_{report_date}.csv"'
    )
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(
        [
            "Quote ID",
            "Status",
            "Flow Type",
            "Client",
            "Origin",
            "Destination",
            "Container Number",
            "Container Size",
            "Loading Date",
            "CBM",
            "Rate per CBM",
            "Rate per Container",
            "Doc & Handling Fee",
            "Amount Quoted",
            "Created At",
        ]
    )

    for quote in Quote.objects.select_related("client").order_by("-created_at", "-id"):
        writer.writerow(
            [
                quote.pk,
                quote.get_status_display(),
                quote.get_flow_type_display(),
                quote.client.name if quote.client else "",
                quote.origin or "",
                quote.destination or "",
                quote.container_number or "",
                quote.get_container_size_display() if quote.container_size else "",
                _fmt_dt(quote.loading_date),
                _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else "",
                (
                    _fmt_number(quote.rate_per_cbm, decimals=2)
                    if quote.rate_per_cbm is not None
                    else ""
                ),
                (
                    _fmt_number(quote.rate_per_container, decimals=2)
                    if quote.rate_per_container is not None
                    else ""
                ),
                _fmt_number(quote.document_handling_fee, decimals=2),
                _fmt_number(quote.amount_quoted, decimals=2),
                _fmt_dt(quote.created_at),
            ]
        )

    log_audit("quote", "export", 0, "CSV Export", request.user)
    return response


@login_required
def export_quotes_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        "Quote ID",
        "Status",
        "Flow Type",
        "Client",
        "Origin",
        "Destination",
        "Container Number",
        "Container Size",
        "Loading Date",
        "CBM",
        "Rate per CBM",
        "Rate per Container",
        "Doc & Handling Fee",
        "Amount Quoted",
        "Created At",
    ]
    rows = [
        [
            quote.pk,
            quote.get_status_display(),
            quote.get_flow_type_display(),
            quote.client.name if quote.client else "",
            quote.origin or "",
            quote.destination or "",
            quote.container_number or "",
            quote.get_container_size_display() if quote.container_size else "",
            _fmt_dt(quote.loading_date),
            _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else "",
            _fmt_money(quote.rate_per_cbm) if quote.rate_per_cbm is not None else "",
            (
                _fmt_money(quote.rate_per_container)
                if quote.rate_per_container is not None
                else ""
            ),
            _fmt_money(quote.document_handling_fee),
            _fmt_money(quote.amount_quoted),
            _fmt_dt(quote.created_at),
        ]
        for quote in Quote.objects.select_related("client").order_by(
            "-created_at", "-id"
        )
    ]
    report_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    response = _pdf_report_response(
        f"quotations_report_{report_date}.pdf", "Quotations Report", headers, rows
    )
    log_audit("quote", "export", 0, "PDF Export", request.user)
    return response


# ===== AUDIT LOGS =====


@login_required
def audit_log_view(request):
    if not _has_full_app_access(request.user):
        messages.error(request, "Permission denied")
        return redirect("dashboard")
    logs = AuditLog.objects.select_related("user")
    total_logs = logs.count()
    page_obj, query_string, page_range = paginate_queryset(
        request, logs, per_page=AUDIT_PAGE_SIZE
    )
    return render(
        request,
        "logistics/audit_logs.html",
        {
            "logs": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "page_range": page_range,
            "total_logs": total_logs,
        },
    )


# ===== UTILITIES =====


def paginate_queryset(request, queryset, per_page=DEFAULT_PAGE_SIZE):
    """Paginate any queryset while preserving existing filters/searches."""
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    query_params = request.GET.copy()
    if "page" in query_params:
        query_params.pop("page")
    query_string = query_params.urlencode()
    if query_string:
        query_string = f"{query_string}&"
    page_range = paginator.get_elided_page_range(page_obj.number)
    return page_obj, query_string, page_range


def log_audit(model_type, action, object_id, object_str, user):
    AuditLog.objects.create(
        user=user,
        model_type=model_type,
        action=action,
        object_id=object_id,
        object_str=object_str,
    )
