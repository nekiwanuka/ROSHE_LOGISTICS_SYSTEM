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
        ('data_entry', 'Data Entry User'),
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='data_entry')
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    def is_superuser_role(self):
        return self.role == 'superuser'
    
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
        if not self.client_id:
            self.client_id = self.generate_unique_id()
        super().save(*args, **kwargs)


class Loading(models.Model):
    """Cargo/Loading management model"""
    loading_id = models.CharField(max_length=50, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='loadings')
    loading_date = models.DateTimeField()
    item_description = models.TextField()
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # in KG
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
        return f"{self.loading_id} - {self.client.name}"


class Transit(models.Model):
    """Transit/Vessel management model"""
    STATUS_CHOICES = (
        ('awaiting', 'Awaiting'),
        ('in_transit', 'In Transit'),
        ('arrived', 'Arrived'),
    )
    
    loading = models.OneToOneField(Loading, on_delete=models.CASCADE, related_name='transit')
    vessel_name = models.CharField(max_length=255)
    boarding_date = models.DateTimeField()
    eta_kampala = models.DateTimeField()  # Estimated Time of Arrival
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='awaiting')
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='created_transits')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.vessel_name} - {self.loading.loading_id}"


class Payment(models.Model):
    """Payment management model"""
    PAYMENT_METHOD_CHOICES = (
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    )
    
    loading = models.OneToOneField(Loading, on_delete=models.CASCADE, related_name='payment')
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
        return f"Payment for {self.loading.loading_id}"
    
    @property
    def invoice_number(self):
        if self.id:
            return f"INV-{self.id:05d}"
        return "INV-DRAFT"
    
    def refresh_totals(self):
        """Recalculate amount paid/balance from related transactions."""
        total_paid = self.transactions.aggregate(total=Sum('amount'))['total'] or 0
        balance = self.amount_charged - total_paid
        Payment.objects.filter(pk=self.pk).update(
            amount_paid=total_paid,
            balance=balance,
            updated_at=timezone.now()
        )
        self.amount_paid = total_paid
        self.balance = balance

    def save(self, *args, **kwargs):
        # Automatically calculate balance
        self.balance = self.amount_charged - self.amount_paid
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
        return f"{self.receipt_number} - {self.payment.loading.loading_id}"
    
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
