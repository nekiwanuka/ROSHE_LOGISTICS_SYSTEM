"""
Database models for the logistics management system
"""
from django.db import models
from django.db.models import Sum
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import secrets
import string

from .constants import COUNTRY_CHOICES, CONTAINER_SIZE_CHOICES


class CustomUser(AbstractUser):
    """Custom user model with role-based access"""
    ROLE_CHOICES = (
        ('superuser', 'Superuser (Admin)'),
        ('managing_director', 'Managing Director'),
        ('manager', 'Manager'),
        ('accountant', 'Accountant'),
        # Backward-compatible internal value; displayed as Front Desk.
        ('data_entry', 'Front Desk Operator'),
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='data_entry')
    phone = models.CharField(max_length=20, blank=True)
    # Optional per-user overrides set by privileged admins.
    # Keys are defined in logistics.permissions.PERM_KEYS.
    permission_overrides = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    def is_superuser_role(self):
        return self.role == 'superuser'

    def is_managing_director_role(self):
        return self.role == 'managing_director'
    
    def is_data_entry_role(self):
        return self.role == 'data_entry'

    def save(self, *args, **kwargs):
        """Keep role/is_staff aligned with Django's superuser flag."""
        if self.is_superuser:
            self.role = 'superuser'
            self.is_staff = True
        super().save(*args, **kwargs)


def _random_code(length=10):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _random_digits(length=10):
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def _normalize_container_number(value):
    """Normalize container numbers consistently.

    Users often type in lower-case or with spaces; store a clean, uppercase value.
    """
    if value is None:
        return value
    text = str(value).strip()
    if not text:
        return text
    text = ''.join(text.split())
    return text.upper()


def _normalize_title_case(value):
    """Capitalize each word (Title Case), while preserving acronyms.

    Examples:
    - "uae - dubai" -> "UAE - Dubai"
    - "cma cgm" -> "CMA CGM"
    - "mombasa" -> "Mombasa"
    """
    if value is None:
        return value

    raw = ' '.join(str(value).strip().split())
    if not raw:
        return raw

    def _format_token(token: str) -> str:
        if not token:
            return token

        # Preserve tokens that are already fully uppercase (letters/digits).
        if token == token.upper() and token != token.lower():
            return token

        # Split common separators while keeping them.
        for sep in ('/', '-', '.'):
            if sep in token:
                parts = token.split(sep)
                return sep.join(_format_token(p) for p in parts)

        # Treat short alphabetic tokens as acronyms.
        if token.isalpha() and 2 <= len(token) <= 4:
            return token.upper()

        # Default: normal title-casing for a word.
        return token[:1].upper() + token[1:].lower()

    words = raw.split(' ')
    return ' '.join(_format_token(w) for w in words)


def _normalize_sentence_case(value):
    """Capitalize only the first letter of the whole string (sentence case)."""
    if value is None:
        return value
    text = ' '.join(str(value).strip().split())
    if not text:
        return text
    lower = text.lower()
    for i, ch in enumerate(lower):
        if ch.isalpha():
            return lower[:i] + ch.upper() + lower[i + 1:]
    return lower


class Client(models.Model):
    """Client management model"""
    client_id = models.CharField(max_length=50, unique=True, editable=False)
    name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField()
    country = models.CharField(max_length=100, choices=COUNTRY_CHOICES, blank=True)
    date_registered = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_clients')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.client_id} - {self.name}"

    @classmethod
    def generate_unique_id(cls):
        """Generate a unique client ID prefixed with RGL."""
        while True:
            candidate = f"RGL{_random_digits(10)}"
            if not cls.objects.filter(client_id=candidate).exists():
                return candidate

    def save(self, *args, **kwargs):
        # Store name-like fields in uppercase to match business rules.
        if self.name is not None:
            self.name = str(self.name).strip().upper()
        if self.company_name is not None:
            self.company_name = str(self.company_name).strip().upper()
        if self.contact_person is not None:
            self.contact_person = str(self.contact_person).strip().upper()

        if not self.client_id:
            self.client_id = self.generate_unique_id()
        super().save(*args, **kwargs)


class Loading(models.Model):
    """Cargo/Loading management model"""

    FLOW_CHOICES = (
        ('lcl', 'LCL (Less Container Load)'),
        ('fcl', 'FCL (Full Container Load)'),
    )

    flow_type = models.CharField(max_length=10, choices=FLOW_CHOICES, default='fcl')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='loadings')
    loading_date = models.DateTimeField()
    item_description = models.TextField(blank=True, null=True)
    # Stored as a decimal; the business meaning is CBM (volume).
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    container_number = models.CharField(max_length=100)
    container_size = models.CharField(max_length=20, choices=CONTAINER_SIZE_CHOICES, blank=True)
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_loadings')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        label = self.container_number or f"Cargo #{self.pk}"
        return f"{label} - {self.client.client_id} - {self.client.name}"

    def save(self, *args, **kwargs):
        self.container_number = _normalize_container_number(self.container_number)
        self.origin = _normalize_sentence_case(self.origin)
        self.destination = _normalize_sentence_case(self.destination)
        super().save(*args, **kwargs)


class Transit(models.Model):
    """Transit/Vessel management model"""
    STATUS_CHOICES = (
        ('awaiting', 'Awaiting'),
        ('in_transit', 'In Transit'),
        ('arrived', 'Arrived'),
    )

    ETA_LOCATION_CHOICES = (
        ('kampala', 'Kampala'),
        ('mombasa', 'Mombasa'),
    )

    shipping_line = models.CharField(max_length=255, blank=True)
    container_number = models.CharField(max_length=100, blank=True)
    boarding_date = models.DateTimeField()
    eta_location = models.CharField(max_length=20, choices=ETA_LOCATION_CHOICES, blank=True)
    eta = models.DateTimeField(null=True, blank=True)  # Estimated Time of Arrival
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='awaiting')
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_transits')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.shipping_line} - {self.container_number}"

    def save(self, *args, **kwargs):
        self.container_number = _normalize_container_number(self.container_number)
        self.shipping_line = _normalize_title_case(self.shipping_line)
        super().save(*args, **kwargs)


class Payment(models.Model):
    """Payment management model"""
    PAYMENT_METHOD_CHOICES = (
        ('cash', 'Cash'),
        ('bank', 'Bank'),
        ('mobile_money', 'Mobile Money'),
        ('cheque', 'Cheque'),
    )
    
    loading = models.OneToOneField(Loading, on_delete=models.CASCADE, related_name='payment')
    rate_per_cbm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rate_per_container = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    document_handling_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    amount_charged = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    receipt_number = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        label = self.loading.container_number or f"Cargo #{self.loading.pk}"
        return f"Payment for {label}"
    
    @property
    def invoice_number(self):
        """Return shipment invoice number formatted as YYMM###.

        - YY: last two digits of year
        - MM: two-digit month
        - ###: sequence number within that month
        """
        if not self.pk:
            return "DRAFT"

        created_at = self.created_at or timezone.now()
        yy = created_at.strftime('%y')
        mm = created_at.strftime('%m')
        monthly_sequence = (
            self.__class__.objects.filter(
                created_at__year=created_at.year,
                created_at__month=created_at.month,
                pk__lte=self.pk,
            ).count()
        )
        return f"{yy}{mm}{monthly_sequence:03d}"
    
    def refresh_totals(self):
        """Recalculate amount paid/balance from related transactions.

        Only approved transactions affect the invoice balance.
        """
        total_paid = (
            self.transactions.filter(verification_status='approved', is_voided=False).aggregate(total=Sum('amount'))[
                'total'
            ]
            or 0
        )
        balance = self.amount_charged - total_paid
        Payment.objects.filter(pk=self.pk).update(
            amount_paid=total_paid,
            balance=balance,
            updated_at=timezone.now()
        )
        self.amount_paid = total_paid
        self.balance = balance

    def save(self, *args, **kwargs):
        # Automatically calculate amount charged from rate fields when possible.
        fee = self.document_handling_fee or 0
        freight_amount = None
        flow = getattr(self.loading, 'flow_type', None)
        if flow == 'lcl' and self.rate_per_cbm is not None and self.loading.weight is not None:
            freight_amount = self.loading.weight * self.rate_per_cbm
        elif flow == 'fcl' and self.rate_per_container is not None:
            freight_amount = self.rate_per_container

        if freight_amount is not None:
            self.amount_charged = freight_amount + fee

        # Automatically calculate balance
        self.balance = self.amount_charged - self.amount_paid
        super().save(*args, **kwargs)


class Quote(models.Model):
    """Client quotation that can be converted into a cargo record + invoice.

    Quotes should not require creating a Cargo (Loading) upfront.
    """

    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('converted', 'Converted to Invoice'),
    )

    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name='quotes',
        null=True,
        blank=True,
    )
    flow_type = models.CharField(max_length=10, choices=Loading.FLOW_CHOICES, default='fcl')

    # Shipment details captured at quotation stage (from client).
    container_number = models.CharField(max_length=100, null=True, blank=True)
    container_size = models.CharField(max_length=20, choices=CONTAINER_SIZE_CHOICES, null=True, blank=True)
    origin = models.CharField(max_length=255, null=True, blank=True)
    destination = models.CharField(max_length=255, null=True, blank=True)
    loading_date = models.DateTimeField(null=True, blank=True)
    item_description = models.TextField(blank=True, null=True)

    # LCL only (CBM provided by client at quotation stage).
    cbm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Optional link once a cargo record has been created from the quote.
    loading = models.OneToOneField(
        Loading,
        on_delete=models.SET_NULL,
        related_name='quote',
        null=True,
        blank=True,
    )
    rate_per_cbm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rate_per_container = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    document_handling_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    amount_quoted = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_quotes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = self.container_number or f"Quote #{self.pk}"
        return f"Quote for {label}"

    def save(self, *args, **kwargs):
        self.container_number = _normalize_container_number(self.container_number)
        self.origin = _normalize_sentence_case(self.origin)
        self.destination = _normalize_sentence_case(self.destination)
        fee = self.document_handling_fee or 0
        quoted = None
        if self.flow_type == 'lcl' and self.rate_per_cbm is not None and self.cbm is not None:
            quoted = (self.cbm * self.rate_per_cbm) + fee
        elif self.flow_type == 'fcl' and self.rate_per_container is not None:
            quoted = self.rate_per_container + fee

        if quoted is not None:
            self.amount_quoted = quoted

        super().save(*args, **kwargs)


class PaymentTransaction(models.Model):
    """Individual payment events supporting partial payments."""

    VERIFICATION_CHOICES = (
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    payment = models.ForeignKey(Payment, related_name='transactions', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=Payment.PAYMENT_METHOD_CHOICES)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default='pending')
    verification_notes = models.TextField(blank=True)

    # Soft-voiding receipts (never hard-delete financial records).
    is_voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='voided_transactions',
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    verified_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='verified_transactions',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='payment_transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-payment_date']
    
    def __str__(self):
        label = self.payment.loading.container_number or f"Cargo #{self.payment.loading.pk}"
        return f"{self.receipt_number} - {label}"
    
    @property
    def receipt_number(self):
        if self.id:
            return f"RCT-{self.id:05d}"
        return "RCT-DRAFT"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.payment.refresh_totals()
    
    def delete(self, *args, **kwargs):
        payment = self.payment
        super().delete(*args, **kwargs)
        payment.refresh_totals()


class ContainerReturn(models.Model):
    """Container return management model"""
    CONDITION_CHOICES = (
        ('good', 'Good'),
        ('damaged', 'Damaged'),
        ('missing', 'Missing'),
    )
    
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('returned', 'Returned'),
        ('damaged_inspected', 'Damaged - Inspected'),
    )
    
    container_number = models.CharField(max_length=100)
    container_size = models.CharField(max_length=20, choices=CONTAINER_SIZE_CHOICES, blank=True)
    loading = models.ForeignKey(Loading, on_delete=models.PROTECT, related_name='container_returns')
    return_date = models.DateTimeField()
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_container_returns')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.container_number} - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        self.container_number = _normalize_container_number(self.container_number)
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """Audit trail for tracking changes"""
    ACTION_CHOICES = (
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
    )
    
    MODEL_CHOICES = (
        ('client', 'Client'),
        ('loading', 'Loading'),
        ('transit', 'Transit'),
        ('quote', 'Quotation'),
        ('payment', 'Payment'),
        ('container_return', 'Container Return'),
        ('user', 'User'),
    )
    
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    model_type = models.CharField(max_length=50, choices=MODEL_CHOICES)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    object_id = models.IntegerField()
    object_str = models.CharField(max_length=255)
    changes = models.JSONField(null=True, blank=True)  # Store what changed
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Audit Logs'
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.get_model_type_display()} ({self.object_str})"
