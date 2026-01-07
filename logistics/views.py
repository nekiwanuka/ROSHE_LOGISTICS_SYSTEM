"""Views for the logistics management system."""
import csv
from decimal import Decimal
from datetime import timedelta
from io import BytesIO

from django.contrib import messages
from django.core.management import call_command
from django.core.mail import EmailMessage
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.paginator import Paginator
from django.db.models import Q, Sum, ProtectedError
from django.conf import settings
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from reportlab.lib import colors
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


DEFAULT_PAGE_SIZE = 20
AUDIT_PAGE_SIZE = 40


FULL_ACCESS_ROLES = {'superuser', 'managing_director'}


def _has_full_app_access(user) -> bool:
    """Full in-app access (System Admin + Managing Director)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in FULL_ACCESS_ROLES


def _deny_if_data_entry_reports(request):
    """Data entry users cannot access reports/exports."""
    if getattr(request.user, 'role', None) == 'data_entry':
        return HttpResponse('Permission denied', status=403)
    return None


def _fmt_dt(value):
    if not value:
        return ''
    try:
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ''


def _fmt_number(value, decimals=2):
    if value is None or value == '':
        return ''
    try:
        return f"{Decimal(str(value)):.{decimals}f}"
    except Exception:
        try:
            return f"{float(value):.{decimals}f}"
        except Exception:
            return str(value)


def _fmt_money(value):
    if value is None or value == '':
        return ''
    try:
        return f"${Decimal(str(value)):,.2f}"
    except Exception:
        return str(value)


def _quote_number(quote):
    if getattr(quote, 'pk', None):
        return f"QTN-{quote.pk:05d}"
    return 'QTN-DRAFT'


def _numeric_part(value, default=None):
    if value is None:
        return default
    try:
        import re

        match = re.search(r'(\d+)(?!.*\d)', str(value))
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
    canvas_obj.setFont('Helvetica-Bold', 8.5)
    canvas_obj.drawString(left, y0 + 7, 'ROSHE LOGISTICS')

    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawRightString(right, y0 + 7, 'www.roshegroup.com')
    canvas_obj.restoreState()


# ===== AUTHENTICATION =====


def login_view(request):
    """Authenticate user credentials and start a session."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, 'Invalid username or password')
    return render(request, 'logistics/login.html')


def logout_view(request):
    """Terminate an authenticated session."""
    logout(request)
    messages.success(request, 'Logged out successfully')
    return redirect('login')


def register_view(request):
    """Create new user accounts (superusers only)."""
    if not request.user.is_authenticated:
        return redirect('login')
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request_user=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} created successfully')
            log_audit('user', 'create', user.id, str(user), request.user)
            return redirect('user_list')
    else:
        form = UserRegistrationForm(request_user=request.user)
    return render(request, 'logistics/register.html', {'form': form})


# ===== DASHBOARD & USERS =====


@login_required
def dashboard(request):
    """Landing page with KPI highlights."""
    context = {
        'total_clients': Client.objects.count(),
        'total_loadings': Loading.objects.count(),
        'total_transits': Transit.objects.count(),
        'outstanding_payments': Payment.objects.filter(balance__gt=0).aggregate(
            Sum('balance')
        )['balance__sum']
        or 0,
        'recent_clients': Client.objects.all()[:5],
        'recent_loadings': Loading.objects.all()[:5],
        'pending_containers': ContainerReturn.objects.filter(status='pending').count(),
        'pending_verifications': PaymentTransaction.objects.filter(verification_status='pending').count(),
        'enable_seed_tools': getattr(settings, 'ENABLE_SEED_TOOLS', False),
    }
    return render(request, 'logistics/dashboard.html', context)


@login_required
def dashboard_reset_keep_users_and_seed(request):
    if not getattr(settings, 'ENABLE_SEED_TOOLS', False):
        # Hide existence of this endpoint in production.
        raise Http404()

    if not getattr(request.user, 'is_superuser', False):
        messages.error(request, 'Permission denied')
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect('dashboard')

    username = (request.POST.get('created_by') or '').strip()
    if not username:
        messages.error(request, 'Please enter a username to own the seeded records.')
        return redirect('dashboard')

    if not CustomUser.objects.filter(username=username).exists():
        messages.error(request, f"User '{username}' not found.")
        return redirect('dashboard')

    try:
        call_command('reset_keep_users_and_seed', yes=True, created_by=username)
    except Exception as exc:
        messages.error(request, f'Failed to reset & reseed: {exc}')
        return redirect('dashboard')

    messages.success(request, f"Database reset and sample data reseeded (owner: {username}).")
    return redirect('dashboard')


@login_required
def user_list(request):
    """List all users (superusers only)."""
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('dashboard')
    users = CustomUser.objects.all()
    page_obj, query_string, page_range = paginate_queryset(request, users)
    return render(
        request,
        'logistics/users/list.html',
        {
            'users': page_obj,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


# ===== CLIENT MANAGEMENT =====


@login_required
def client_list(request):
    clients = Client.objects.all()
    search = request.GET.get('search', '')
    if search:
        clients = clients.filter(
            Q(client_id__icontains=search)
            | Q(name__icontains=search)
            | Q(contact_person__icontains=search)
        )
    page_obj, query_string, page_range = paginate_queryset(request, clients)
    return render(
        request,
        'logistics/clients/list.html',
        {
            'clients': page_obj,
            'search': search,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            client.created_by = request.user
            client.save()
            messages.success(request, f'Client {client.name} created successfully')
            log_audit('client', 'create', client.id, str(client), request.user)
            return redirect('client_detail', pk=client.id)
    else:
        form = ClientForm()
    return render(
        request,
        'logistics/clients/form.html',
        {'form': form, 'title': 'Create Client'},
    )


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    return render(
        request,
        'logistics/clients/detail.html',
        {'client': client, 'loadings': client.loadings.all()},
    )


@login_required
def client_update(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Client updated successfully')
            log_audit('client', 'update', client.id, str(client), request.user)
            return redirect('client_detail', pk=client.id)
    else:
        form = ClientForm(instance=client)
    return render(
        request,
        'logistics/clients/form.html',
        {'form': form, 'title': 'Update Client', 'client': client},
    )


@login_required
def client_delete(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('client_list')
    client = get_object_or_404(Client, pk=pk)
    client_str = str(client)
    client_id = client.id
    try:
        client.delete()
    except ProtectedError:
        messages.error(
            request,
            'This client cannot be deleted while there are cargo/loadings linked to them. Remove or reassign those records first.',
        )
        return redirect('client_detail', pk=client_id)
    messages.success(request, 'Client deleted successfully')
    log_audit('client', 'delete', client_id, client_str, request.user)
    return redirect('client_list')

# ===== LOADING MANAGEMENT =====


@login_required
def loading_list(request):
    loadings = Loading.objects.select_related('client')
    search = request.GET.get('search', '')
    if search:
        loadings = loadings.filter(
            Q(container_number__icontains=search)
            | Q(client__name__icontains=search)
            | Q(origin__icontains=search)
            | Q(destination__icontains=search)
        )
    page_obj, query_string, page_range = paginate_queryset(request, loadings)
    return render(
        request,
        'logistics/loadings/list.html',
        {
            'loadings': page_obj,
            'search': search,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


@login_required
def loading_create(request):
    if request.method == 'POST':
        form = LoadingForm(request.POST)
        if form.is_valid():
            loading = form.save(commit=False)
            loading.created_by = request.user
            loading.save()
            messages.success(request, 'Cargo created successfully')
            log_audit('loading', 'create', loading.id, str(loading), request.user)
            return redirect('loading_detail', pk=loading.id)
    else:
        form = LoadingForm()
    return render(
        request,
        'logistics/loadings/form.html',
        {'form': form, 'title': 'Create Loading'},
    )


@login_required
def loading_detail(request, pk):
    loading = get_object_or_404(Loading, pk=pk)
    transit = (
        Transit.objects.filter(container_number=loading.container_number)
        .order_by('-created_at')
        .first()
    )
    context = {
        'loading': loading,
        'transit': transit,
        'has_transit': transit is not None,
        'has_payment': hasattr(loading, 'payment'),
    }
    return render(request, 'logistics/loadings/detail.html', context)


@login_required
def loading_update(request, pk):
    loading = get_object_or_404(Loading, pk=pk)
    if request.method == 'POST':
        form = LoadingForm(request.POST, instance=loading)
        if form.is_valid():
            form.save()
            messages.success(request, 'Loading updated successfully')
            log_audit('loading', 'update', loading.id, str(loading), request.user)
            return redirect('loading_detail', pk=loading.id)
    else:
        form = LoadingForm(instance=loading)
    return render(
        request,
        'logistics/loadings/form.html',
        {'form': form, 'title': 'Update Loading', 'loading': loading},
    )


@login_required
def loading_delete(request, pk):
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('loading_list')
    loading = get_object_or_404(Loading, pk=pk)
    loading_str = str(loading)
    loading_id = loading.id
    loading.delete()
    messages.success(request, 'Loading deleted successfully')
    log_audit('loading', 'delete', loading_id, loading_str, request.user)
    return redirect('loading_list')


# ===== TRANSIT MANAGEMENT =====


@login_required
def transit_list(request):
    transits = Transit.objects.all()
    status = request.GET.get('status', '')
    if status:
        transits = transits.filter(status=status)
    page_obj, query_string, page_range = paginate_queryset(request, transits)
    return render(
        request,
        'logistics/transits/list.html',
        {
            'transits': page_obj,
            'status_filter': status,
            'status_choices': Transit.STATUS_CHOICES,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


@login_required
def transit_create(request):
    if request.method == 'POST':
        form = TransitForm(request.POST)
        if form.is_valid():
            transit = form.save(commit=False)
            transit.created_by = request.user
            transit.save()
            messages.success(request, 'Transit created successfully')
            log_audit('transit', 'create', transit.id, str(transit), request.user)
            return redirect('transit_list')
    else:
        form = TransitForm()
        container_number = request.GET.get('container_number')
        if container_number:
            form.fields['container_number'].initial = container_number
    return render(
        request,
        'logistics/transits/form.html',
        {'form': form, 'title': 'Create Transit'},
    )


@login_required
def transit_update(request, pk):
    transit = get_object_or_404(Transit, pk=pk)
    if request.method == 'POST':
        form = TransitForm(request.POST, instance=transit)
        if form.is_valid():
            form.save()
            messages.success(request, 'Transit updated successfully')
            log_audit('transit', 'update', transit.id, str(transit), request.user)
            return redirect('transit_list')
    else:
        form = TransitForm(instance=transit)
    return render(
        request,
        'logistics/transits/form.html',
        {'form': form, 'title': 'Update Transit'},
    )


# ===== PAYMENT MANAGEMENT =====


@login_required
def payment_list(request):
    payments = Payment.objects.select_related('loading__client')
    filter_type = request.GET.get('filter', '')
    if filter_type == 'outstanding':
        payments = payments.filter(balance__gt=0)
    elif filter_type == 'paid':
        payments = payments.filter(balance=0)
    page_obj, query_string, page_range = paginate_queryset(request, payments)
    totals = {
        'total_charged': Payment.objects.aggregate(Sum('amount_charged'))['amount_charged__sum'] or 0,
        'total_paid': Payment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0,
        'total_outstanding': Payment.objects.filter(balance__gt=0).aggregate(Sum('balance'))['balance__sum']
        or 0,
    }
    can_view_financial_totals = request.user.role != 'data_entry'
    if not can_view_financial_totals:
        totals = {key: None for key in totals}
    context = {
        'payments': page_obj,
        'filter_type': filter_type,
        **totals,
        'can_view_financial_totals': can_view_financial_totals,
        'page_obj': page_obj,
        'query_string': query_string,
        'page_range': page_range,
    }
    return render(request, 'logistics/payments/list.html', context)


@login_required
def payment_create(request, loading_id=None):
    if request.user.role == 'data_entry':
        messages.error(request, 'Permission denied')
        return redirect('payment_list')
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.created_by = request.user
            payment.save()
            messages.success(request, 'Invoice created successfully')
            log_audit('payment', 'create', payment.id, str(payment), request.user)
            return redirect('payment_detail', pk=payment.id)
    else:
        form = PaymentForm()
        if loading_id:
            form.fields['loading'].initial = loading_id
    return render(
        request,
        'logistics/payments/form.html',
        {'form': form, 'title': 'Create Invoice', 'payment': None},
    )


@login_required
def payment_update(request, pk):
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot edit payments')
        return redirect('payment_list')
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    if request.method == 'POST':
        form = PaymentForm(request.POST, instance=payment)
        if form.is_valid():
            form.save()
            messages.success(request, 'Invoice updated successfully')
            log_audit('payment', 'update', payment.id, str(payment), request.user)
            return redirect('payment_detail', pk=payment.id)
    else:
        form = PaymentForm(instance=payment)
    return render(
        request,
        'logistics/payments/form.html',
        {'form': form, 'title': 'Update Invoice', 'payment': payment},
    )


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    transactions = payment.transactions.select_related('created_by', 'verified_by').all()
    if request.method == 'POST':
        action = request.POST.get('action', 'create_transaction')
        if action == 'verify_transaction':
            if not _has_full_app_access(request.user):
                messages.error(request, 'Permission denied')
                return redirect('payment_detail', pk=pk)
            transaction = get_object_or_404(
                payment.transactions.select_related('payment'),
                pk=request.POST.get('transaction_id'),
            )
            new_status = request.POST.get('verification_status', 'pending')
            valid_statuses = {choice for choice, _ in PaymentTransaction.VERIFICATION_CHOICES}
            if new_status not in valid_statuses:
                messages.error(request, 'Invalid verification status selected.')
                return redirect('payment_detail', pk=pk)
            notes = request.POST.get('verification_notes', '').strip()
            transaction.verification_status = new_status
            transaction.verification_notes = notes
            if new_status == 'pending':
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
            return redirect('payment_detail', pk=pk)
        else:
            if request.user.role == 'data_entry':
                messages.error(request, 'Permission denied')
                return redirect('payment_detail', pk=pk)
            form = PaymentTransactionForm(request.POST)
            if form.is_valid():
                transaction = form.save(commit=False)
                transaction.payment = payment
                transaction.created_by = request.user
                transaction.save()
                log_audit(
                    'payment',
                    'update',
                    payment.id,
                    f'Payment transaction {transaction.receipt_number}',
                    request.user,
                )
                messages.success(request, f'Recorded payment of ${transaction.amount:,.2f}')
                return redirect('payment_detail', pk=pk)
    else:
        form = PaymentTransactionForm(
            initial={
                'payment_method': payment.payment_method or 'cash',
                'payment_date': timezone.now(),
            }
        )
    context = {
        'payment': payment,
        'transactions': transactions,
        'transaction_form': form,
        'verification_choices': PaymentTransaction.VERIFICATION_CHOICES,
        'can_verify': _has_full_app_access(request.user),
        'can_record_payment': request.user.role != 'data_entry',
    }
    return render(request, 'logistics/payments/detail.html', context)


@login_required
def payment_invoice(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    preview_param = (request.GET.get('preview') or '').strip().lower()
    preview = preview_param in {'1', 'true', 'yes', 'y'}
    buffer = BytesIO()
    loading = payment.loading
    client = loading.client

    issue_date = payment.created_at if payment.created_at else timezone.now()
    due_date = issue_date + timedelta(days=7)
    amount_due = payment.balance
    fee = payment.document_handling_fee or 0

    primary = colors.HexColor('#003366')
    accent = colors.HexColor('#f2cb3f')

    styles = getSampleStyleSheet()
    normal = styles['Normal']
    normal.fontName = 'Helvetica'
    normal.fontSize = 9
    normal.leading = 12

    heading = styles['Heading4']
    heading.fontName = 'Helvetica-Bold'
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles['BodyText']
    small.fontName = 'Helvetica'
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        logo_box = 44
        canvas_obj.setFillColor(primary)
        canvas_obj.rect(left, top - logo_box + 8, logo_box, logo_box, fill=1, stroke=0)

        logo_path = finders.find('images/roshe_logo.svg')
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

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont('Helvetica-Bold', 12)
        canvas_obj.drawString(company_x, top, 'ROSHE LOGISTICS')
        canvas_obj.setFont('Helvetica', 8.5)
        canvas_obj.setFillColor(colors.black)
        canvas_obj.drawString(company_x, top - 12, 'Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202')
        canvas_obj.drawString(company_x, top - 24, '+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com')
        canvas_obj.drawString(company_x, top - 36, 'www.roshegroup.com')

        # Shipment invoice label (yellow background, black text)
        label_text = f"SHIPMENT INVOICE {payment.invoice_number}"
        canvas_obj.setFont('Helvetica-Bold', 12)
        label_w = canvas_obj.stringWidth(label_text, 'Helvetica-Bold', 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0)
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
        title=f"Shipment Invoice {payment.invoice_number}",
    )

    bill_to_lines = [
        '<b>BILL TO</b>',
        f"{client.name}",
        f"Phone: {client.phone}",
    ]
    if client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph('<br/>'.join(bill_to_lines), normal)

    invoice_meta = Paragraph(
        '<b>Shipment Invoice No:</b> ' + payment.invoice_number + '<br/>'
        + '<b>Container Number:</b> ' + (loading.container_number or '—') + '<br/>'
        + '<b>Invoice Date:</b> ' + issue_date.strftime('%Y-%m-%d') + '<br/>'
        + '<b>Payment Due:</b> ' + due_date.strftime('%Y-%m-%d') + '<br/>'
        + '<b>Amount Due (USD):</b> $' + f"{amount_due:,.2f}",
        normal,
    )

    flow = getattr(loading, 'flow_type', None)
    shipment_lines = [
        '<b>SHIPMENT</b>',
        f"Route: {loading.origin} to {loading.destination}",
        f"Loading Date: {loading.loading_date.strftime('%Y-%m-%d') if loading.loading_date else '—'}",
    ]
    if flow == 'fcl':
        if loading.container_size:
            shipment_lines.append(f"Container Size: {loading.get_container_size_display()}")
    else:
        cbm_value = f"{loading.weight:.2f} CBM" if loading.weight is not None else '—'
        shipment_lines.append(f"CBM: {cbm_value}")
    shipment_details = Paragraph('<br/>'.join(shipment_lines), normal)

    info_table = Table(
        [[bill_to, invoice_meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign='LEFT',
    )
    info_table.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]
        )
    )

    if flow == 'lcl':
        qty_label = f"{loading.weight:.2f}" if loading.weight is not None else '—'
        rate_label = f"{payment.rate_per_cbm:,.2f}" if payment.rate_per_cbm is not None else '—'
        freight_amount = (loading.weight * payment.rate_per_cbm) if (loading.weight is not None and payment.rate_per_cbm is not None) else None
    else:
        qty_label = '1'
        rate_label = f"{payment.rate_per_container:,.2f}" if payment.rate_per_container is not None else '—'
        freight_amount = payment.rate_per_container if payment.rate_per_container is not None else None

    freight_amount_label = f"{freight_amount:,.2f}" if freight_amount is not None else '—'

    route = f"{loading.origin} to {loading.destination}"
    freight_item = f"Shipment Charges ({route})"

    qty_header = 'CBM' if flow == 'lcl' else 'Qty'
    items = [
        ['Items', qty_header, 'Rate', 'Amount'],
        [freight_item, qty_label, rate_label, freight_amount_label],
    ]
    if fee and fee > 0:
        items.append(['Document & Handling Fees', '', '', f"{fee:,.2f}"])

    items_table = Table(
        items,
        colWidths=[doc.width * 0.52, doc.width * 0.16, doc.width * 0.16, doc.width * 0.16],
        hAlign='LEFT',
    )
    items_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F2F2F2')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]
        )
    )

    total_amount = payment.amount_charged
    totals_table = Table(
        [
            ['', '', 'Total', f"{total_amount:,.2f}"],
            ['', '', 'Amount Due (USD)', f"{amount_due:,.2f}"],
        ],
        colWidths=[doc.width * 0.52, doc.width * 0.16, doc.width * 0.16, doc.width * 0.16],
        hAlign='LEFT',
    )
    totals_table.setStyle(
        TableStyle(
            [
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('LINEABOVE', (2, 0), (-1, 0), 0.7, colors.black),
                ('LINEBELOW', (2, -1), (-1, -1), 0.7, colors.black),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph('<b>Notes / Terms</b>', heading),
        Paragraph('1. Invoice valid for 7 days from date of issue.', small),
        Paragraph('2. Partial payments are recorded; outstanding balance must be cleared before release.', small),
        Paragraph('3. Thank you for choosing ROSHE LOGISTICS.', small),
        Spacer(1, 6),
        Paragraph('<b>Bank Details</b>', heading),
        Paragraph('Bank details are available on request. Please contact ROSHE LOGISTICS.', small),
    ]

    story = [
        info_table,
        Spacer(1, 12),
        shipment_details,
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
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    disposition = 'inline' if preview else 'attachment'
    client_id = getattr(client, 'client_id', None) or 'NOCLIENT'
    response['Content-Disposition'] = (
        f'{disposition}; filename="{client_id}_INV_{payment.invoice_number}.pdf"'
    )
    return response


@login_required
def payment_invoice_email(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    loading = payment.loading
    client = loading.client

    default_to = client.email or ''
    default_subject = f"ROSHE LOGISTICS - Shipment Invoice {payment.invoice_number}"
    default_message = (
        f"Dear {client.name},\n\n"
        f"Please find attached the shipment invoice {payment.invoice_number} for container {loading.container_number}.\n\n"
        "Regards,\nROSHE LOGISTICS"
    )

    if request.method == 'POST':
        form = SendDocumentEmailForm(request.POST)
        if form.is_valid():
            try:
                pdf_bytes = payment_invoice(request, pk).content
                email = EmailMessage(
                    subject=form.cleaned_data['subject'],
                    body=form.cleaned_data['message'] or '',
                    to=[form.cleaned_data['to_email']],
                )
                client_id = getattr(client, 'client_id', None) or 'NOCLIENT'
                email.attach(
                    filename=f"{client_id}_INV_{payment.invoice_number}.pdf",
                    content=pdf_bytes,
                    mimetype='application/pdf',
                )
                email.send(fail_silently=False)
            except Exception as exc:
                messages.error(request, f'Failed to send email: {exc}')
                return redirect('payment_detail', pk=payment.pk)

            messages.success(request, f"Invoice emailed to {form.cleaned_data['to_email']} (attached).")
            return redirect('payment_detail', pk=payment.pk)
    else:
        form = SendDocumentEmailForm(
            initial={'to_email': default_to, 'subject': default_subject, 'message': default_message}
        )

    return render(
        request,
        'logistics/documents/send_email.html',
        {
            'form': form,
            'doc_label': 'Invoice',
            'doc_meta': f"Invoice {payment.invoice_number} · Container {loading.container_number}",
            'back_url': reverse('payment_detail', kwargs={'pk': payment.pk}),
        },
    )


@login_required
def payment_receipt(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related('payment__loading__client', 'created_by', 'verified_by'),
        pk=transaction_id,
    )
    preview_param = (request.GET.get('preview') or '').strip().lower()
    preview = preview_param in {'1', 'true', 'yes', 'y'}
    payment = transaction.payment
    if transaction.verification_status != 'approved':
        messages.error(request, 'This payment has not been verified yet.')
        return redirect('payment_detail', pk=payment.pk)
    paid_up_to = (
        payment.transactions.filter(pk__lte=transaction.pk).aggregate(total=Sum('amount'))['total']
        or transaction.amount
    )
    balance_after = payment.amount_charged - paid_up_to

    buffer = BytesIO()
    loading = payment.loading
    client = loading.client

    primary = colors.HexColor('#003366')
    accent = colors.HexColor('#f2cb3f')

    styles = getSampleStyleSheet()
    normal = styles['Normal']
    normal.fontName = 'Helvetica'
    normal.fontSize = 9
    normal.leading = 12

    heading = styles['Heading4']
    heading.fontName = 'Helvetica-Bold'
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles['BodyText']
    small.fontName = 'Helvetica'
    small.fontSize = 8
    small.leading = 10

    def draw_header(canvas_obj, doc):
        width, height = A4
        left = doc.leftMargin
        right = width - doc.rightMargin
        top = height - doc.topMargin + 95

        # Logo with blue background (only behind the logo)
        logo_box = 44
        canvas_obj.setFillColor(primary)
        canvas_obj.rect(left, top - logo_box + 8, logo_box, logo_box, fill=1, stroke=0)

        logo_path = finders.find('images/roshe_logo.svg')
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

        # Company block
        company_x = left + 60
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont('Helvetica-Bold', 12)
        canvas_obj.drawString(company_x, top, 'ROSHE LOGISTICS')
        canvas_obj.setFont('Helvetica', 8.5)
        canvas_obj.drawString(company_x, top - 12, 'Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202')
        canvas_obj.drawString(company_x, top - 24, '+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com')
        canvas_obj.drawString(company_x, top - 36, 'www.roshegroup.com')

        # Receipt label (yellow background, black text)
        label_text = f"PAYMENT RECEIPT {transaction.receipt_number}"
        canvas_obj.setFont('Helvetica-Bold', 12)
        label_w = canvas_obj.stringWidth(label_text, 'Helvetica-Bold', 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0)
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
        '<b>RECEIVED FROM</b><br/>'
        f"{client.name}<br/>"
        f"Phone: {client.phone}",
        normal,
    )

    payment_lines = [
        '<b>PAYMENT DETAILS</b>',
        f"Shipment Invoice No: {payment.invoice_number}",
        f"Container Number: {loading.container_number or '—'}",
        f"Payment Date: {transaction.payment_date.strftime('%Y-%m-%d %H:%M')}",
        f"Method: {transaction.get_payment_method_display()}",
    ]
    if transaction.reference:
        payment_lines.append(f"Reference: {transaction.reference}")
    payment_details = Paragraph('<br/>'.join(payment_lines), normal)

    top_table = Table(
        [[received_from, payment_details]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign='LEFT',
    )
    top_table.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]
        )
    )

    flow = getattr(loading, 'flow_type', None)
    shipment_lines = [
        '<b>SHIPMENT</b>',
        f"Route: {loading.origin} to {loading.destination}",
        f"Loading Date: {loading.loading_date.strftime('%Y-%m-%d') if loading.loading_date else '—'}",
    ]
    if flow == 'fcl':
        if loading.container_size:
            shipment_lines.append(f"Container Size: {loading.get_container_size_display()}")
    else:
        cbm_value = f"{loading.weight:.2f} CBM" if loading.weight is not None else '—'
        shipment_lines.append(f"CBM: {cbm_value}")
    shipment_details = Paragraph('<br/>'.join(shipment_lines), normal)

    summary_rows = [
        ['Summary', 'Amount (USD)'],
        ['Amount Paid (this receipt)', f"{transaction.amount:,.2f}"],
        ['Paid Up To', f"{paid_up_to:,.2f}"],
        ['Outstanding After Payment', f"{balance_after:,.2f}"],
    ]
    summary_table = Table(
        summary_rows,
        colWidths=[doc.width * 0.65, doc.width * 0.35],
        hAlign='LEFT',
    )
    summary_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F2F2F2')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]
        )
    )

    verification_note = 'Verified'
    if transaction.verified_by:
        verification_note = (
            f"Verified by {transaction.verified_by.username} on "
            f"{transaction.verified_at.strftime('%Y-%m-%d %H:%M') if transaction.verified_at else '—'}"
        )

    audit = [
        Paragraph('<b>Notes</b>', heading),
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
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    disposition = 'inline' if preview else 'attachment'
    client_id = getattr(client, 'client_id', None) or 'NOCLIENT'
    receipt_digits = _numeric_part(transaction.receipt_number, default=f"{transaction.pk:05d}")
    response['Content-Disposition'] = (
        f'{disposition}; filename="{client_id}_RCT_{receipt_digits}.pdf"'
    )
    return response


@login_required
def payment_receipt_email(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related('payment__loading__client'),
        pk=transaction_id,
    )
    payment = transaction.payment
    loading = payment.loading
    client = loading.client

    if transaction.verification_status != 'approved':
        messages.error(request, 'This payment has not been verified yet.')
        return redirect('payment_detail', pk=payment.pk)

    default_to = client.email or ''
    default_subject = f"ROSHE LOGISTICS - Receipt {transaction.receipt_number}"
    default_message = (
        f"Dear {client.name},\n\n"
        f"Please find attached the payment receipt {transaction.receipt_number} for container {loading.container_number}.\n\n"
        "Regards,\nROSHE LOGISTICS"
    )

    if request.method == 'POST':
        form = SendDocumentEmailForm(request.POST)
        if form.is_valid():
            try:
                pdf_bytes = payment_receipt(request, transaction_id).content
                email = EmailMessage(
                    subject=form.cleaned_data['subject'],
                    body=form.cleaned_data['message'] or '',
                    to=[form.cleaned_data['to_email']],
                )
                client_id = getattr(client, 'client_id', None) or 'NOCLIENT'
                receipt_digits = _numeric_part(transaction.receipt_number, default=f"{transaction.pk:05d}")
                email.attach(
                    filename=f"{client_id}_RCT_{receipt_digits}.pdf",
                    content=pdf_bytes,
                    mimetype='application/pdf',
                )
                email.send(fail_silently=False)
            except Exception as exc:
                messages.error(request, f'Failed to send email: {exc}')
                return redirect('payment_detail', pk=payment.pk)

            messages.success(request, f"Receipt emailed to {form.cleaned_data['to_email']} (attached).")
            return redirect('payment_detail', pk=payment.pk)
    else:
        form = SendDocumentEmailForm(
            initial={'to_email': default_to, 'subject': default_subject, 'message': default_message}
        )

    return render(
        request,
        'logistics/documents/send_email.html',
        {
            'form': form,
            'doc_label': 'Receipt',
            'doc_meta': f"Receipt {transaction.receipt_number} · Container {loading.container_number}",
            'back_url': reverse('receipt_list'),
        },
    )


# ===== QUOTATIONS =====


@login_required
def quote_list(request):
    quotes = Quote.objects.select_related('client', 'loading')
    page_obj, query_string, page_range = paginate_queryset(request, quotes)
    return render(
        request,
        'logistics/quotations/list.html',
        {
            'quotes': page_obj,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


@login_required
def quote_create(request):
    if request.method == 'POST':
        form = QuoteForm(request.POST)
        if form.is_valid():
            quote = form.save(commit=False)
            quote.created_by = request.user
            quote.save()
            messages.success(request, 'Quotation created successfully')
            log_audit('quote', 'create', quote.id, str(quote), request.user)
            return redirect('quote_detail', quote_id=quote.id)
    else:
        form = QuoteForm()
    return render(
        request,
        'logistics/quotations/form.html',
        {'form': form, 'title': 'Create Quotation', 'quote': None},
    )


@login_required
def quote_detail(request, quote_id):
    quote = get_object_or_404(Quote.objects.select_related('client', 'loading'), pk=quote_id)
    flow = quote.flow_type
    fee = quote.document_handling_fee or Decimal('0')

    qty = None
    rate = None
    freight_amount = None
    unit_label = ''

    if flow == 'lcl':
        qty = quote.cbm
        rate = quote.rate_per_cbm
        unit_label = 'CBM'
        if qty is not None and rate is not None:
            freight_amount = qty * rate
    else:
        qty = Decimal('1')
        rate = quote.rate_per_container
        unit_label = 'Container'
        if rate is not None:
            freight_amount = rate

    total = quote.amount_quoted

    context = {
        'quote': quote,
        'breakdown': {
            'flow': flow,
            'qty': qty,
            'rate': rate,
            'unit_label': unit_label,
            'freight_amount': freight_amount,
            'fee': fee,
            'total': total,
        },
    }
    return render(request, 'logistics/quotations/detail.html', context)


@login_required
def quote_pdf(request, quote_id):
    quote = get_object_or_404(Quote.objects.select_related('client'), pk=quote_id)
    client = quote.client
    client_id = getattr(client, 'client_id', None) or 'NOCLIENT'
    preview = request.GET.get('preview') == '1'
    quote_no = _quote_number(quote)

    primary = colors.HexColor('#003366')
    accent = colors.HexColor('#f2cb3f')

    styles = getSampleStyleSheet()
    normal = styles['BodyText']
    normal.fontName = 'Helvetica'
    normal.fontSize = 9
    normal.leading = 12

    heading = styles['Heading4']
    heading.fontName = 'Helvetica-Bold'
    heading.fontSize = 10
    heading.leading = 12
    heading.textColor = primary

    small = styles['BodyText']
    small.fontName = 'Helvetica'
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

        logo_path = finders.find('images/roshe_logo.svg')
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
        canvas_obj.setFont('Helvetica-Bold', 12)
        canvas_obj.drawString(company_x, top, 'ROSHE LOGISTICS')
        canvas_obj.setFont('Helvetica', 8.5)
        canvas_obj.drawString(company_x, top - 12, 'Plot 13 Mukwano Courts, Buganda Road · Floor 2 · Rooms 201–202')
        canvas_obj.drawString(company_x, top - 24, '+256 788 239000 · +86 134 1613 7544 · info@roshegroup.com')
        canvas_obj.drawString(company_x, top - 36, 'www.roshegroup.com')

        label_text = f"SHIPMENT QUOTATION {quote_no}"
        canvas_obj.setFont('Helvetica-Bold', 12)
        label_w = canvas_obj.stringWidth(label_text, 'Helvetica-Bold', 12) + 16
        label_h = 20
        label_x = right - label_w
        label_y = top - 2
        canvas_obj.setFillColor(accent)
        canvas_obj.roundRect(label_x, label_y - label_h + 4, label_w, label_h, 6, fill=1, stroke=0)
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
        title=f"Shipment Quotation {quote_no}",
    )

    bill_to_lines = [
        '<b>BILL TO</b>',
        f"{client.name if client else '—'}",
        f"Client ID: {client_id}",
    ]
    if client and client.phone:
        bill_to_lines.append(f"Phone: {client.phone}")
    if client and client.email:
        bill_to_lines.append(f"Email: {client.email}")
    if client and client.address:
        bill_to_lines.append(client.address)
    bill_to = Paragraph('<br/>'.join(bill_to_lines), normal)

    meta_lines = [
        f"<b>Quotation No:</b> {quote_no}",
        f"<b>Status:</b> {quote.get_status_display()}",
        f"<b>Date:</b> {_fmt_dt(quote.created_at) or '—'}",
        f"<b>Container Number:</b> {quote.container_number or '—'}",
        f"<b>Route:</b> {(quote.origin or '—')} to {(quote.destination or '—')}",
    ]
    meta = Paragraph('<br/>'.join(meta_lines), normal)

    info_table = Table(
        [[bill_to, meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
        hAlign='LEFT',
    )
    info_table.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]
        )
    )

    fee = quote.document_handling_fee or Decimal('0')
    if quote.flow_type == 'lcl':
        qty_label = _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else '—'
        rate_label = _fmt_number(quote.rate_per_cbm, decimals=2) if quote.rate_per_cbm is not None else '—'
        freight_amount = (quote.cbm * quote.rate_per_cbm) if (quote.cbm is not None and quote.rate_per_cbm is not None) else None
        unit_label = 'CBM'
    else:
        qty_label = '1'
        rate_label = _fmt_number(quote.rate_per_container, decimals=2) if quote.rate_per_container is not None else '—'
        freight_amount = quote.rate_per_container if quote.rate_per_container is not None else None
        unit_label = 'Container'

    freight_amount_label = _fmt_number(freight_amount, decimals=2) if freight_amount is not None else '—'
    route = f"{quote.origin or '—'} to {quote.destination or '—'}"
    freight_item = f"Shipment Charges ({route})"

    items = [
        ['Items', unit_label, 'Rate', 'Amount'],
        [freight_item, qty_label, rate_label, freight_amount_label],
    ]
    if fee and fee > 0:
        items.append(['Document & Handling Fees', '', '', _fmt_number(fee, decimals=2)])

    items_table = Table(
        items,
        colWidths=[doc.width * 0.52, doc.width * 0.16, doc.width * 0.16, doc.width * 0.16],
        hAlign='LEFT',
    )
    items_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F2F2F2')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOX', (0, 0), (-1, -1), 0.7, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.7, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]
        )
    )

    totals_table = Table(
        [
            ['', '', 'Total Quoted (USD)', _fmt_number(quote.amount_quoted, decimals=2)],
        ],
        colWidths=[doc.width * 0.52, doc.width * 0.16, doc.width * 0.16, doc.width * 0.16],
        hAlign='LEFT',
    )
    totals_table.setStyle(
        TableStyle(
            [
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('LINEABOVE', (2, 0), (-1, 0), 0.7, colors.black),
                ('LINEBELOW', (2, -1), (-1, -1), 0.7, colors.black),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )

    notes = [
        Paragraph('<b>Notes / Terms</b>', heading),
        Paragraph('1. Quotation valid for 7 days from date of issue.', small),
        Paragraph('2. Prices may change due to carrier / customs adjustments.', small),
        Paragraph('3. Thank you for choosing ROSHE LOGISTICS.', small),
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
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    disposition = 'inline' if preview else 'attachment'
    response['Content-Disposition'] = (
        f'{disposition}; filename="{client_id}_QTN_{quote.pk:05d}.pdf"'
    )
    return response


@login_required
def quote_update(request, quote_id):
    quote = get_object_or_404(Quote.objects.select_related('client', 'loading'), pk=quote_id)
    if request.method == 'POST':
        form = QuoteForm(request.POST, instance=quote)
        if form.is_valid():
            form.save()
            messages.success(request, 'Quotation updated successfully')
            log_audit('quote', 'update', quote.id, str(quote), request.user)
            return redirect('quote_detail', quote_id=quote.id)
    else:
        form = QuoteForm(instance=quote)
    return render(
        request,
        'logistics/quotations/form.html',
        {'form': form, 'title': 'Update Quotation', 'quote': quote},
    )


@login_required
def quote_delete(request, quote_id):
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('quote_list')
    quote = get_object_or_404(Quote, pk=quote_id)
    quote_str = str(quote)
    quote_pk = quote.pk
    quote.delete()
    messages.success(request, 'Quotation deleted successfully')
    log_audit('quote', 'delete', quote_pk, quote_str, request.user)
    return redirect('quote_list')


@login_required
def quote_convert_to_invoice(request, quote_id):
    if request.method != 'POST':
        return redirect('quote_detail', quote_id=quote_id)
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot convert quotations to invoices')
        return redirect('quote_detail', quote_id=quote_id)

    quote = get_object_or_404(Quote.objects.select_related('client', 'loading'), pk=quote_id)

    if quote.status != 'accepted':
        messages.error(request, 'This quotation must be marked as Accepted before converting to an invoice.')
        return redirect('quote_detail', quote_id=quote_id)

    loading = quote.loading
    if loading is None:
        loading = Loading.objects.create(
            flow_type=quote.flow_type,
            client=quote.client,
            loading_date=quote.loading_date,
            item_description=quote.item_description,
            weight=quote.cbm,
            container_number=quote.container_number,
            container_size=quote.container_size,
            origin=quote.origin,
            destination=quote.destination,
            created_by=request.user,
        )
        quote.loading = loading

    existing_payment = getattr(loading, 'payment', None)
    if existing_payment:
        quote.status = 'converted'
        quote.save(update_fields=['status', 'loading', 'updated_at'])
        messages.info(request, 'An invoice already exists for this cargo. Opened the existing invoice.')
        return redirect('payment_detail', pk=existing_payment.pk)

    payment = Payment.objects.create(
        loading=loading,
        rate_per_cbm=quote.rate_per_cbm,
        rate_per_container=quote.rate_per_container,
        document_handling_fee=quote.document_handling_fee or 0,
        amount_charged=0,
        amount_paid=0,
        balance=0,
        created_by=request.user,
    )
    quote.status = 'converted'
    quote.save(update_fields=['status', 'loading', 'updated_at'])

    log_audit('quote', 'update', quote.id, f'{quote} converted to invoice', request.user)
    log_audit('payment', 'create', payment.id, str(payment), request.user)
    messages.success(request, 'Quotation converted to invoice successfully')
    return redirect('payment_detail', pk=payment.pk)


# ===== RECEIPTS =====


@login_required
def receipt_list(request):
    receipts = PaymentTransaction.objects.select_related('payment__loading__client', 'created_by', 'verified_by')
    search = (request.GET.get('search') or '').strip()
    if search:
        receipts = receipts.filter(
            Q(receipt_number__icontains=search)
            | Q(payment__loading__container_number__icontains=search)
            | Q(payment__loading__client__name__icontains=search)
            | Q(payment__loading__client__client_id__icontains=search)
        )
    page_obj, query_string, page_range = paginate_queryset(request, receipts)
    return render(
        request,
        'logistics/receipts/list.html',
        {
            'receipts': page_obj,
            'search': search,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


# ===== CONTAINER RETURNS =====


@login_required
def container_return_list(request):
    containers = ContainerReturn.objects.select_related('loading')
    status = request.GET.get('status', '')
    if status:
        containers = containers.filter(status=status)
    page_obj, query_string, page_range = paginate_queryset(request, containers)
    return render(
        request,
        'logistics/containers/list.html',
        {
            'containers': page_obj,
            'status_filter': status,
            'status_choices': ContainerReturn.STATUS_CHOICES,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
        },
    )


@login_required
def container_return_create(request):
    if request.method == 'POST':
        form = ContainerReturnForm(request.POST)
        if form.is_valid():
            container = form.save(commit=False)
            container.created_by = request.user
            container.save()
            messages.success(request, 'Container return recorded')
            log_audit('container_return', 'create', container.id, str(container), request.user)
            return redirect('container_return_list')
    else:
        form = ContainerReturnForm()
    return render(
        request,
        'logistics/containers/form.html',
        {'form': form, 'title': 'Record Container Return'},
    )


@login_required
def container_return_update(request, pk):
    container = get_object_or_404(ContainerReturn, pk=pk)
    if request.method == 'POST':
        form = ContainerReturnForm(request.POST, instance=container)
        if form.is_valid():
            form.save()
            messages.success(request, 'Container return updated successfully')
            log_audit('container_return', 'update', container.id, str(container), request.user)
            return redirect('container_return_list')
    else:
        form = ContainerReturnForm(instance=container)
    return render(
        request,
        'logistics/containers/form.html',
        {'form': form, 'title': 'Update Container Return'},
    )


# ===== REPORTS & EXPORTS =====


def _pdf_report_response(filename, title, headers, rows):
    """Render tabular data into a downloadable PDF report."""
    normalized_rows = [
        [str(value) if value is not None else '' for value in row]
        for row in (rows or [['' for _ in headers]])
    ]
    buffer = BytesIO()
    page_size = landscape(A4)
    primary = colors.HexColor('#003366')
    accent = colors.HexColor('#f2cb3f')

    generated_at = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')

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

        canvas_obj.saveState()
        canvas_obj.setFillColor(primary)
        canvas_obj.setFont('Helvetica-Bold', 11)
        canvas_obj.drawString(left, height - 28, 'ROSHE LOGISTICS')

        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont('Helvetica-Bold', 13)
        canvas_obj.drawString(left, height - 46, title)

        canvas_obj.setFont('Helvetica', 9)
        canvas_obj.setFillColor(colors.HexColor('#333333'))
        canvas_obj.drawRightString(right, height - 28, f"Generated: {generated_at}")
        canvas_obj.drawRightString(right, height - 46, f"Page {canvas_obj.getPageNumber()}")

        canvas_obj.setStrokeColor(accent)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(left, height - 52, right, height - 52)
        canvas_obj.restoreState()

        _draw_brand_footer(canvas_obj, doc_obj, primary=primary, accent=accent)

    styles = getSampleStyleSheet()

    title_style = styles['Heading1'].clone('report_title_stub')
    title_style.fontName = 'Helvetica-Bold'
    title_style.fontSize = 1  # canvas draws the actual title
    title_style.leading = 1

    cell_style = styles['BodyText'].clone('report_cell')
    cell_style.fontName = 'Helvetica'
    cell_style.fontSize = 8.5
    cell_style.leading = 10
    cell_style.textColor = colors.black

    header_style = styles['BodyText'].clone('report_header')
    header_style.fontName = 'Helvetica-Bold'
    header_style.fontSize = 9
    header_style.leading = 11
    header_style.textColor = colors.white

    def as_para(text, style):
        # Keep it simple and safe; ReportLab Paragraph handles basic wrapping.
        return Paragraph(str(text or '').replace('\n', '<br/>'), style)

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
                max_len = max(max_len, len(str(r[col_idx] or '')))
        lengths.append(max(6, min(max_len, 40)))
    total = sum(lengths) or 1
    col_widths = [max(0.75 * inch, doc.width * (l / total)) for l in lengths]
    # Adjust if rounding pushes beyond available width.
    width_sum = sum(col_widths)
    if width_sum > doc.width:
        scale = doc.width / width_sum
        col_widths = [w * scale for w in col_widths]

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign='LEFT')

    numeric_keywords = (
        'amount',
        'balance',
        'rate',
        'cbm',
        'weight',
    )
    numeric_cols = [
        idx
        for idx, h in enumerate(headers)
        if any(k in str(h).strip().lower() for k in numeric_keywords)
    ]

    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), primary),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.black),
            ]
        )
    )

    for col_idx in numeric_cols:
        table.setStyle(
            TableStyle(
                [
                    ('ALIGN', (col_idx, 1), (col_idx, -1), 'RIGHT'),
                ]
            )
        )

    story = [Paragraph(title, title_style), Spacer(1, 6)]
    story.append(table)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def reports_dashboard(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    totals = {
        'total_revenue': Payment.objects.aggregate(Sum('amount_charged'))['amount_charged__sum'] or 0,
        'total_paid': Payment.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0,
        'outstanding_balance': Payment.objects.filter(balance__gt=0).aggregate(Sum('balance'))['balance__sum']
        or 0,
    }
    can_view_financial_totals = request.user.role != 'data_entry'
    if not can_view_financial_totals:
        totals = {key: None for key in totals}
    context = {
        'total_clients': Client.objects.count(),
        'total_loadings': Loading.objects.count(),
        'in_transit_count': Transit.objects.filter(status='in_transit').count(),
        **totals,
        'can_view_financial_totals': can_view_financial_totals,
    }
    return render(request, 'logistics/reports/dashboard.html', context)


@login_required
def export_clients_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="clients_report.csv"'
    # Excel-friendly UTF-8 BOM
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow([
        'Client ID',
        'Name',
        'Contact Person',
        'Phone',
        'Address',
        'Date Registered',
        'Remarks',
    ])
    for client in Client.objects.all().order_by('client_id'):
        writer.writerow(
            [
                client.client_id,
                client.name,
                client.contact_person,
                client.phone,
                client.address,
                _fmt_dt(client.date_registered),
                client.remarks or '',
            ]
        )
    log_audit('client', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_clients_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = ['Client ID', 'Name', 'Contact Person', 'Phone', 'Address', 'Date Registered', 'Remarks']
    rows = [
        [
            client.client_id,
            client.name,
            client.contact_person,
            client.phone,
            client.address,
            _fmt_dt(client.date_registered),
            client.remarks or '',
        ]
        for client in Client.objects.all().order_by('client_id')
    ]
    response = _pdf_report_response('clients_report.pdf', 'Clients Report', headers, rows)
    log_audit('client', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_shipments_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="shipments_report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(
        [
            'Flow Type',
            'Client',
            'Loading Date',
            'Item Description',
            'CBM',
            'Container Number',
            'Container Size',
            'Origin',
            'Destination',
        ]
    )
    for loading in Loading.objects.select_related('client').order_by('-loading_date', '-id'):
        writer.writerow(
            [
                loading.get_flow_type_display(),
                loading.client.name,
                _fmt_dt(loading.loading_date),
                loading.item_description or '',
                _fmt_number(loading.weight, decimals=2) if loading.weight is not None else '',
                loading.container_number,
                loading.get_container_size_display() if loading.container_size else '',
                loading.origin,
                loading.destination,
            ]
        )
    log_audit('loading', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_shipments_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        'Flow Type',
        'Client',
        'Loading Date',
        'Item Description',
        'CBM',
        'Container Number',
        'Container Size',
        'Origin',
        'Destination',
    ]
    rows = [
        [
            loading.get_flow_type_display(),
            loading.client.name,
            _fmt_dt(loading.loading_date),
            loading.item_description or '',
            _fmt_number(loading.weight, decimals=2) if loading.weight is not None else '',
            loading.container_number,
            loading.get_container_size_display() if loading.container_size else '',
            loading.origin,
            loading.destination,
        ]
        for loading in Loading.objects.select_related('client').order_by('-loading_date', '-id')
    ]
    response = _pdf_report_response('shipments_report.pdf', 'Shipments Report', headers, rows)
    log_audit('loading', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_payments_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="payments_report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(
        [
            'Container Number',
            'Flow Type',
            'Client',
            'Rate per CBM',
            'Rate per Container',
            'Amount Charged',
            'Amount Paid',
            'Balance',
            'Payment Date',
            'Payment Method',
            'Receipt Number',
        ]
    )
    for payment in Payment.objects.select_related('loading__client').order_by('-id'):
        writer.writerow(
            [
                payment.loading.container_number,
                payment.loading.get_flow_type_display(),
                payment.loading.client.name,
                _fmt_number(payment.rate_per_cbm, decimals=2) if payment.rate_per_cbm is not None else '',
                _fmt_number(payment.rate_per_container, decimals=2) if payment.rate_per_container is not None else '',
                _fmt_number(payment.amount_charged, decimals=2),
                _fmt_number(payment.amount_paid, decimals=2),
                _fmt_number(payment.balance, decimals=2),
                _fmt_dt(payment.payment_date),
                payment.get_payment_method_display() if payment.payment_method else '',
                payment.receipt_number or '',
            ]
        )
    log_audit('payment', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_payments_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        'Container Number',
        'Flow Type',
        'Client',
        'Rate per CBM',
        'Rate per Container',
        'Amount Charged',
        'Amount Paid',
        'Balance',
        'Payment Date',
        'Payment Method',
        'Receipt Number',
    ]
    rows = [
        [
            payment.loading.container_number,
            payment.loading.get_flow_type_display(),
            payment.loading.client.name,
            f"${payment.rate_per_cbm:,.2f}" if payment.rate_per_cbm is not None else '',
            f"${payment.rate_per_container:,.2f}" if payment.rate_per_container is not None else '',
            f"${payment.amount_charged:,.2f}",
            f"${payment.amount_paid:,.2f}",
            f"${payment.balance:,.2f}",
            payment.payment_date.strftime('%Y-%m-%d %H:%M') if payment.payment_date else '',
            payment.get_payment_method_display() if payment.payment_method else '',
            payment.receipt_number or '',
        ]
        for payment in Payment.objects.select_related('loading__client')
    ]
    response = _pdf_report_response('payments_report.pdf', 'Payments Report', headers, rows)
    log_audit('payment', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_containers_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="container_returns_report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(
        [
            'Container Number',
            'Container Size',
            'Cargo Container',
            'Client',
            'Return Date',
            'Condition',
            'Status',
            'Remarks',
        ]
    )
    for container in ContainerReturn.objects.select_related('loading__client').order_by('-return_date', '-id'):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (container.loading.get_container_size_display() if container.loading.container_size else '')
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
                container.remarks or '',
            ]
        )
    log_audit('container_return', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_containers_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        'Container Number',
        'Container Size',
        'Cargo Container',
        'Client',
        'Return Date',
        'Condition',
        'Status',
        'Remarks',
    ]
    rows = []
    for container in ContainerReturn.objects.select_related('loading__client').order_by('-return_date', '-id'):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (container.loading.get_container_size_display() if container.loading.container_size else '')
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
                container.remarks or '',
            ]
        )
    response = _pdf_report_response('container_returns_report.pdf', 'Container Returns Report', headers, rows)
    log_audit('container_return', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_quotes_csv(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="quotations_report.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(
        [
            'Quote ID',
            'Status',
            'Flow Type',
            'Client',
            'Origin',
            'Destination',
            'Container Number',
            'Container Size',
            'Loading Date',
            'CBM',
            'Rate per CBM',
            'Rate per Container',
            'Doc & Handling Fee',
            'Amount Quoted',
            'Created At',
        ]
    )

    for quote in Quote.objects.select_related('client').order_by('-created_at', '-id'):
        writer.writerow(
            [
                quote.pk,
                quote.get_status_display(),
                quote.get_flow_type_display(),
                quote.client.name if quote.client else '',
                quote.origin or '',
                quote.destination or '',
                quote.container_number or '',
                quote.get_container_size_display() if quote.container_size else '',
                _fmt_dt(quote.loading_date),
                _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else '',
                _fmt_number(quote.rate_per_cbm, decimals=2) if quote.rate_per_cbm is not None else '',
                _fmt_number(quote.rate_per_container, decimals=2) if quote.rate_per_container is not None else '',
                _fmt_number(quote.document_handling_fee, decimals=2),
                _fmt_number(quote.amount_quoted, decimals=2),
                _fmt_dt(quote.created_at),
            ]
        )

    log_audit('quote', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_quotes_pdf(request):
    denied = _deny_if_data_entry_reports(request)
    if denied:
        return denied
    headers = [
        'Quote ID',
        'Status',
        'Flow Type',
        'Client',
        'Origin',
        'Destination',
        'Container Number',
        'Container Size',
        'Loading Date',
        'CBM',
        'Rate per CBM',
        'Rate per Container',
        'Doc & Handling Fee',
        'Amount Quoted',
        'Created At',
    ]
    rows = [
        [
            quote.pk,
            quote.get_status_display(),
            quote.get_flow_type_display(),
            quote.client.name if quote.client else '',
            quote.origin or '',
            quote.destination or '',
            quote.container_number or '',
            quote.get_container_size_display() if quote.container_size else '',
            _fmt_dt(quote.loading_date),
            _fmt_number(quote.cbm, decimals=2) if quote.cbm is not None else '',
            _fmt_money(quote.rate_per_cbm) if quote.rate_per_cbm is not None else '',
            _fmt_money(quote.rate_per_container) if quote.rate_per_container is not None else '',
            _fmt_money(quote.document_handling_fee),
            _fmt_money(quote.amount_quoted),
            _fmt_dt(quote.created_at),
        ]
        for quote in Quote.objects.select_related('client').order_by('-created_at', '-id')
    ]
    response = _pdf_report_response('quotations_report.pdf', 'Quotations Report', headers, rows)
    log_audit('quote', 'export', 0, 'PDF Export', request.user)
    return response


# ===== AUDIT LOGS =====


@login_required
def audit_log_view(request):
    if not _has_full_app_access(request.user):
        messages.error(request, 'Permission denied')
        return redirect('dashboard')
    logs = AuditLog.objects.select_related('user')
    total_logs = logs.count()
    page_obj, query_string, page_range = paginate_queryset(request, logs, per_page=AUDIT_PAGE_SIZE)
    return render(
        request,
        'logistics/audit_logs.html',
        {
            'logs': page_obj,
            'page_obj': page_obj,
            'query_string': query_string,
            'page_range': page_range,
            'total_logs': total_logs,
        },
    )


# ===== UTILITIES =====


def paginate_queryset(request, queryset, per_page=DEFAULT_PAGE_SIZE):
    """Paginate any queryset while preserving existing filters/searches."""
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    query_string = query_params.urlencode()
    if query_string:
        query_string = f'{query_string}&'
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
