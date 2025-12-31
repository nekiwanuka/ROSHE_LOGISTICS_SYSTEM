"""Views for the logistics management system."""
import csv
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .forms import (
    ClientForm,
    ContainerReturnForm,
    LoadingForm,
    PaymentForm,
    PaymentTransactionForm,
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
    Transit,
)


DEFAULT_PAGE_SIZE = 20
AUDIT_PAGE_SIZE = 40


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
    if request.user.role != 'superuser':
        messages.error(request, 'Only superusers can create new users')
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} created successfully')
            log_audit('user', 'create', user.id, str(user), request.user)
            return redirect('user_list')
    else:
        form = UserRegistrationForm()
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
    }
    return render(request, 'logistics/dashboard.html', context)


@login_required
def user_list(request):
    """List all users (superusers only)."""
    if request.user.role != 'superuser':
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
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot edit clients')
        return redirect('client_list')
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
    if request.user.role != 'superuser':
        messages.error(request, 'Only superusers can delete clients')
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
            Q(loading_id__icontains=search)
            | Q(client__name__icontains=search)
            | Q(origin__icontains=search)
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
            messages.success(request, f'Loading {loading.loading_id} created successfully')
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
    context = {
        'loading': loading,
        'has_transit': hasattr(loading, 'transit'),
        'has_payment': hasattr(loading, 'payment'),
    }
    return render(request, 'logistics/loadings/detail.html', context)


@login_required
def loading_update(request, pk):
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot edit loadings')
        return redirect('loading_list')
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
    if request.user.role != 'superuser':
        messages.error(request, 'Only superusers can delete loadings')
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
    transits = Transit.objects.select_related('loading')
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
def transit_create(request, loading_id=None):
    if request.method == 'POST':
        form = TransitForm(request.POST)
        if form.is_valid():
            transit = form.save(commit=False)
            transit.created_by = request.user
            transit.save()
            messages.success(request, 'Transit created successfully')
            log_audit('transit', 'create', transit.id, str(transit), request.user)
            return redirect('loading_detail', pk=transit.loading.id)
    else:
        form = TransitForm()
        if loading_id:
            form.fields['loading'].initial = loading_id
    return render(
        request,
        'logistics/transits/form.html',
        {'form': form, 'title': 'Create Transit'},
    )


@login_required
def transit_update(request, pk):
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot edit transits')
        return redirect('transit_list')
    transit = get_object_or_404(Transit, pk=pk)
    if request.method == 'POST':
        form = TransitForm(request.POST, instance=transit)
        if form.is_valid():
            form.save()
            messages.success(request, 'Transit updated successfully')
            log_audit('transit', 'update', transit.id, str(transit), request.user)
            return redirect('loading_detail', pk=transit.loading.id)
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
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.created_by = request.user
            payment.save()
            messages.success(request, 'Payment created successfully')
            log_audit('payment', 'create', payment.id, str(payment), request.user)
            return redirect('payment_detail', pk=payment.id)
    else:
        form = PaymentForm()
        if loading_id:
            form.fields['loading'].initial = loading_id
    return render(
        request,
        'logistics/payments/form.html',
        {'form': form, 'title': 'Create Payment', 'payment': None},
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
            messages.success(request, 'Payment updated successfully')
            log_audit('payment', 'update', payment.id, str(payment), request.user)
            return redirect('payment_detail', pk=payment.id)
    else:
        form = PaymentForm(instance=payment)
    return render(
        request,
        'logistics/payments/form.html',
        {'form': form, 'title': 'Update Payment', 'payment': payment},
    )


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    transactions = payment.transactions.select_related('created_by', 'verified_by').all()
    if request.method == 'POST':
        action = request.POST.get('action', 'create_transaction')
        if action == 'verify_transaction':
            if request.user.role != 'superuser':
                messages.error(request, 'Only superusers can verify payments.')
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
        'can_verify': request.user.role == 'superuser',
    }
    return render(request, 'logistics/payments/detail.html', context)


@login_required
def payment_invoice(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('loading__client'), pk=pk)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    header_height = 85
    primary = colors.HexColor('#003366')
    accent = colors.HexColor('#FFD700')

    pdf.setFillColor(primary)
    pdf.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont('Helvetica-Bold', 22)
    pdf.drawString(margin, height - 40, 'Roshe Group Logistics Portal')
    pdf.setFont('Helvetica', 12)
    pdf.drawString(margin, height - 60, 'Premium Freight & Customs Solutions')
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawRightString(width - margin, height - 45, 'INVOICE')
    pdf.setFont('Helvetica', 11)
    pdf.drawRightString(width - margin, height - 60, payment.invoice_number)

    pdf.setFillColor(colors.black)
    info_top = height - header_height - 30
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin, info_top, 'Invoice Details')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(margin, info_top - 18, f"Issue Date: {timezone.now().strftime('%Y-%m-%d')}")
    pdf.drawString(margin, info_top - 34, f"Prepared By: {payment.created_by.username}")
    pdf.drawString(margin, info_top - 50, f"Loading ID: {payment.loading.loading_id}")

    bill_top = info_top - 80
    box_width = (width / 2) - margin
    pdf.roundRect(margin, bill_top - 110, box_width - 10, 110, 8, stroke=1)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin + 10, bill_top - 15, 'Bill To:')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(margin + 10, bill_top - 32, payment.loading.client.name)
    pdf.drawString(margin + 10, bill_top - 48, f"Client ID: {payment.loading.client.client_id}")
    pdf.drawString(margin + 10, bill_top - 64, f"Contact: {payment.loading.client.phone}")
    pdf.drawString(margin + 10, bill_top - 80, payment.loading.client.address[:60])

    ship_left = margin + box_width + 5
    pdf.roundRect(ship_left, bill_top - 110, box_width - 10, 110, 8, stroke=1)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(ship_left + 10, bill_top - 15, 'Shipment')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(
        ship_left + 10,
        bill_top - 32,
        f"Route: {payment.loading.origin} -> {payment.loading.destination}",
    )
    pdf.drawString(
        ship_left + 10,
        bill_top - 48,
        f"Container: {payment.loading.container_number}",
    )
    container_size_label = (
        payment.loading.get_container_size_display() if payment.loading.container_size else 'N/A'
    )
    pdf.drawString(
        ship_left + 10,
        bill_top - 64,
        f"Container Size: {container_size_label}",
    )
    weight_label = f"{payment.loading.weight} KG" if payment.loading.weight else 'N/A'
    pdf.drawString(
        ship_left + 10,
        bill_top - 80,
        f"Weight: {weight_label}",
    )
    pdf.drawString(
        ship_left + 10,
        bill_top - 96,
        f"Loading Date: {payment.loading.loading_date.strftime('%Y-%m-%d')}",
    )

    summary_top = bill_top - 120
    pdf.setFillColor(accent)
    pdf.rect(margin, summary_top - 80, width - (2 * margin), 80, fill=1, stroke=0)
    pdf.setFillColor(primary)
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin + 15, summary_top - 25, 'Amount Due')
    pdf.drawString(margin + 190, summary_top - 25, 'Amount Paid')
    pdf.drawString(margin + 365, summary_top - 25, 'Balance')
    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawString(margin + 15, summary_top - 55, f"${payment.amount_charged:,.2f}")
    pdf.drawString(margin + 190, summary_top - 55, f"${payment.amount_paid:,.2f}")
    pdf.drawString(margin + 365, summary_top - 55, f"${payment.balance:,.2f}")

    pdf.setFillColor(colors.black)
    notes_top = summary_top - 110
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin, notes_top, 'Notes')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(
        margin,
        notes_top - 16,
        '1. Invoice valid for 7 days from date of issue.',
    )
    pdf.drawString(
        margin,
        notes_top - 30,
        '2. Partial payments are recorded; outstanding balance must be cleared before release.',
    )
    pdf.drawString(margin, notes_top - 44, '3. Thank you for choosing Roshe Group Logistics Portal.')

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="invoice_{payment.invoice_number}.pdf"'
    )
    return response


@login_required
def payment_receipt(request, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related('payment__loading__client', 'created_by', 'verified_by'),
        pk=transaction_id,
    )
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
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    header_height = 70
    accent = colors.HexColor('#22A699')

    pdf.setFillColor(accent)
    pdf.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawString(margin, height - 35, 'PAYMENT RECEIPT')
    pdf.setFont('Helvetica', 11)
    pdf.drawRightString(width - margin, height - 30, transaction.receipt_number)

    pdf.setFillColor(colors.black)
    info_top = height - header_height - 30
    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin, info_top, 'Received From')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(margin, info_top - 18, payment.loading.client.name)
    pdf.drawString(margin, info_top - 34, f"Invoice: {payment.invoice_number}")
    pdf.drawString(
        margin,
        info_top - 50,
        f"Route: {payment.loading.origin} -> {payment.loading.destination}",
    )

    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawString(margin, info_top - 80, 'Amount Details')
    pdf.setFont('Helvetica', 11)
    pdf.drawString(margin, info_top - 100, f"Amount Paid: ${transaction.amount:,.2f}")
    pdf.drawString(
        margin,
        info_top - 118,
        f"Payment Date: {transaction.payment_date.strftime('%Y-%m-%d')}",
    )
    pdf.drawString(margin, info_top - 136, f"Method: {transaction.get_payment_method_display()}")
    if transaction.reference:
        pdf.drawString(margin, info_top - 154, f"Reference: {transaction.reference}")
    pdf.drawString(
        margin,
        info_top - 172,
        f"Outstanding After Payment: ${balance_after:,.2f}",
    )

    pdf.setFont('Helvetica', 10)
    pdf.drawString(
        margin,
        info_top - 210,
        f"Recorded By: {transaction.created_by.username} on {transaction.created_at.strftime('%Y-%m-%d %H:%M')}",
    )
    pdf.drawString(margin, info_top - 226, 'Thank you for your business.')

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="receipt_{transaction.receipt_number}.pdf"'
    )
    return response


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
    if request.user.role == 'data_entry':
        messages.error(request, 'You cannot edit container returns')
        return redirect('container_return_list')
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
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=24,
        rightMargin=24,
        topMargin=36,
        bottomMargin=24,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles['Heading1']), Spacer(1, 10)]
    data = [headers] + normalized_rows
    col_widths = [doc.width / len(headers)] * len(headers)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def reports_dashboard(request):
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
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="clients_report.csv"'
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
    for client in Client.objects.all():
        writer.writerow(
            [
                client.client_id,
                client.name,
                client.contact_person,
                client.phone,
                client.address,
                client.date_registered.strftime('%Y-%m-%d %H:%M'),
                client.remarks or '',
            ]
        )
    log_audit('client', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_clients_pdf(request):
    headers = ['Client ID', 'Name', 'Contact Person', 'Phone', 'Address', 'Date Registered', 'Remarks']
    rows = [
        [
            client.client_id,
            client.name,
            client.contact_person,
            client.phone,
            client.address,
            client.date_registered.strftime('%Y-%m-%d %H:%M'),
            client.remarks or '',
        ]
        for client in Client.objects.all()
    ]
    response = _pdf_report_response('clients_report.pdf', 'Clients Report', headers, rows)
    log_audit('client', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_shipments_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="shipments_report.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            'Loading ID',
            'Client',
            'Loading Date',
            'Item Description',
            'Weight (KG)',
            'Container Number',
            'Container Size',
            'Origin',
            'Destination',
        ]
    )
    for loading in Loading.objects.select_related('client'):
        writer.writerow(
            [
                loading.loading_id,
                loading.client.name,
                loading.loading_date.strftime('%Y-%m-%d %H:%M'),
                loading.item_description,
                loading.weight,
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
    headers = [
        'Loading ID',
        'Client',
        'Loading Date',
        'Item Description',
        'Weight (KG)',
        'Container Number',
        'Container Size',
        'Origin',
        'Destination',
    ]
    rows = [
        [
            loading.loading_id,
            loading.client.name,
            loading.loading_date.strftime('%Y-%m-%d %H:%M'),
            loading.item_description,
            loading.weight or '',
            loading.container_number,
            loading.get_container_size_display() if loading.container_size else '',
            loading.origin,
            loading.destination,
        ]
        for loading in Loading.objects.select_related('client')
    ]
    response = _pdf_report_response('shipments_report.pdf', 'Shipments Report', headers, rows)
    log_audit('loading', 'export', 0, 'PDF Export', request.user)
    return response


@login_required
def export_payments_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="payments_report.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            'Loading ID',
            'Client',
            'Amount Charged',
            'Amount Paid',
            'Balance',
            'Payment Date',
            'Payment Method',
            'Receipt Number',
        ]
    )
    for payment in Payment.objects.select_related('loading__client'):
        writer.writerow(
            [
                payment.loading.loading_id,
                payment.loading.client.name,
                payment.amount_charged,
                payment.amount_paid,
                payment.balance,
                payment.payment_date.strftime('%Y-%m-%d %H:%M') if payment.payment_date else '',
                payment.get_payment_method_display() if payment.payment_method else '',
                payment.receipt_number or '',
            ]
        )
    log_audit('payment', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_payments_pdf(request):
    headers = [
        'Loading ID',
        'Client',
        'Amount Charged',
        'Amount Paid',
        'Balance',
        'Payment Date',
        'Payment Method',
        'Receipt Number',
    ]
    rows = [
        [
            payment.loading.loading_id,
            payment.loading.client.name,
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
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="container_returns_report.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            'Container Number',
            'Container Size',
            'Loading ID',
            'Client',
            'Return Date',
            'Condition',
            'Status',
            'Remarks',
        ]
    )
    for container in ContainerReturn.objects.select_related('loading__client'):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (container.loading.get_container_size_display() if container.loading.container_size else '')
        )
        writer.writerow(
            [
                container.container_number,
                size_display,
                container.loading.loading_id,
                container.loading.client.name,
                container.return_date.strftime('%Y-%m-%d %H:%M'),
                container.get_condition_display(),
                container.get_status_display(),
                container.remarks or '',
            ]
        )
    log_audit('container_return', 'export', 0, 'CSV Export', request.user)
    return response


@login_required
def export_containers_pdf(request):
    headers = [
        'Container Number',
        'Container Size',
        'Loading ID',
        'Client',
        'Return Date',
        'Condition',
        'Status',
        'Remarks',
    ]
    rows = []
    for container in ContainerReturn.objects.select_related('loading__client'):
        size_display = (
            container.get_container_size_display()
            if container.container_size
            else (container.loading.get_container_size_display() if container.loading.container_size else '')
        )
        rows.append(
            [
                container.container_number,
                size_display,
                container.loading.loading_id,
                container.loading.client.name,
                container.return_date.strftime('%Y-%m-%d %H:%M'),
                container.get_condition_display(),
                container.get_status_display(),
                container.remarks or '',
            ]
        )
    response = _pdf_report_response('container_returns_report.pdf', 'Container Returns Report', headers, rows)
    log_audit('container_return', 'export', 0, 'PDF Export', request.user)
    return response


# ===== AUDIT LOGS =====


@login_required
def audit_log_view(request):
    if request.user.role != 'superuser':
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
