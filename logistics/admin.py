"""
Django admin configuration for the logistics app
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser,
    Client,
    Loading,
    Transit,
    Payment,
    Quote,
    ContainerReturn,
    AuditLog,
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Custom user admin"""

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "role",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2", "role"),
            },
        ),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Client admin"""

    list_display = ("client_id", "name", "contact_person", "phone", "date_registered")
    search_fields = ("client_id", "name", "contact_person")
    list_filter = ("date_registered",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Loading)
class LoadingAdmin(admin.ModelAdmin):
    """Loading admin"""

    list_display = (
        "container_number",
        "item_number",
        "flow_type",
        "cargo_type",
        "client",
        "loading_date",
        "origin",
        "destination",
        "ctns",
        "gross_weight",
        "air_rate_basis",
        "rate_per_kg",
        "airline",
    )
    search_fields = (
        "container_number",
        "item_number",
        "item_description",
        "airline",
        "size_per_carton",
        "client__name",
        "cargo_type",
    )
    list_filter = (
        "flow_type",
        "cargo_type",
        "loading_date",
        "origin",
        "destination",
        "airline",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Transit)
class TransitAdmin(admin.ModelAdmin):
    """Transit admin"""

    list_display = (
        "shipping_line",
        "container_number",
        "boarding_date",
        "eta_location",
        "eta",
        "status",
    )
    search_fields = ("shipping_line", "container_number")
    list_filter = ("status", "boarding_date")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Payment admin"""

    list_display = (
        "loading",
        "pvoc_fee",
        "amount_charged",
        "amount_paid",
        "balance",
        "payment_date",
    )
    search_fields = (
        "loading__container_number",
        "loading__item_number",
        "receipt_number",
    )
    list_filter = ("payment_date", "payment_method")
    readonly_fields = ("balance", "created_at", "updated_at")


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    """Quote admin"""

    list_display = (
        "client",
        "cargo_type",
        "flow_type",
        "amount_quoted",
        "air_rate_basis",
        "status",
        "created_at",
    )
    search_fields = (
        "container_number",
        "item_number",
        "client__name",
        "origin",
        "destination",
    )
    list_filter = ("cargo_type", "status", "created_at")
    readonly_fields = ("amount_quoted", "created_at", "updated_at")


@admin.register(ContainerReturn)
class ContainerReturnAdmin(admin.ModelAdmin):
    """Container return admin"""

    list_display = ("container_number", "loading", "return_date", "condition", "status")
    search_fields = ("container_number", "loading__container_number")
    list_filter = ("status", "condition", "return_date")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Audit log admin - Read only"""

    list_display = ("timestamp", "user", "action", "model_type", "object_str")
    search_fields = ("user__username", "object_str")
    list_filter = ("action", "model_type", "timestamp")
    readonly_fields = (
        "user",
        "model_type",
        "action",
        "object_id",
        "object_str",
        "changes",
        "timestamp",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
