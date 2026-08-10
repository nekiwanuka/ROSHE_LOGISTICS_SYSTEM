"""
Django forms for the logistics management system
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import (
    CustomUser,
    Client,
    Loading,
    Transit,
    Payment,
    PaymentTransaction,
    ContainerReturn,
)
from .models import Quote

from .permissions import ROLE_DEFAULTS, get_app_permissions


def _decimal_text_widget(*, css_class: str = "form-control", placeholder: str = ""):
    """Prefer text inputs for decimals to avoid browser rounding/coercion from type=number."""
    attrs = {
        "class": css_class,
        "inputmode": "decimal",
        "autocomplete": "off",
        # Accept digits and a single decimal separator; keep it permissive for mobile keyboards.
        "pattern": r"[0-9]*[\.,]?[0-9]*",
    }
    if placeholder:
        attrs["placeholder"] = placeholder
    return forms.TextInput(attrs=attrs)


class UserRegistrationForm(UserCreationForm):
    """Form for creating new users"""

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Username"}
        ),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"})
    )
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "First Name"}
        ),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Last Name"}
        ),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Phone Number"}
        ),
    )
    role = forms.ChoiceField(
        choices=CustomUser.ROLE_CHOICES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    perm_manage_users = forms.BooleanField(
        required=False,
        label="Can manage users",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_manage_users"}
        ),
    )

    perm_create_clients = forms.BooleanField(
        required=False,
        label="Can create clients",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_clients"}
        ),
    )
    perm_create_quotations = forms.BooleanField(
        required=False,
        label="Can create quotations",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_quotations"}
        ),
    )
    perm_create_invoices = forms.BooleanField(
        required=False,
        label="Can create invoices",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_invoices"}
        ),
    )
    perm_create_receipts = forms.BooleanField(
        required=False,
        label="Can record receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_receipts"}
        ),
    )
    perm_access_reports = forms.BooleanField(
        required=False,
        label="Can access reports/exports",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_access_reports"}
        ),
    )

    perm_view_revenue = forms.BooleanField(
        required=False,
        label="Can view revenue totals",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_view_revenue"}
        ),
    )
    perm_approve_verify = forms.BooleanField(
        required=False,
        label="Can approve/verify receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_approve_verify"}
        ),
    )
    perm_void_unvoid = forms.BooleanField(
        required=False,
        label="Can void/unvoid receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_void_unvoid"}
        ),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Password"}
        ),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Confirm Password"}
        ),
    )

    class Meta:
        model = CustomUser
        fields = ("username", "email", "first_name", "last_name", "phone", "role")

    def __init__(self, *args, **kwargs):
        request_user = kwargs.pop("request_user", None)
        can_configure_permissions = bool(kwargs.pop("can_configure_permissions", False))
        super().__init__(*args, **kwargs)

        # Role assignment rules:
        # - Superuser: may create Managing Director, Manager, Accountant, Front Desk.
        # - Managing Director: may create Manager, Accountant, Front Desk.
        # - Manager: may create Accountant, Front Desk.
        # - Others: no user creation rights.
        creator_role = getattr(request_user, "role", None)
        is_super = bool(getattr(request_user, "is_superuser", False))

        if is_super:
            allowed = ["managing_director", "manager", "accountant", "data_entry"]
        elif creator_role == "managing_director":
            allowed = ["manager", "accountant", "data_entry"]
        elif creator_role == "manager":
            allowed = ["accountant", "data_entry"]
        else:
            allowed = []

        # Never allow creating a superuser via the UI.
        role_map = dict(CustomUser.ROLE_CHOICES)
        self.fields["role"].choices = [
            (key, role_map[key]) for key in allowed if key in role_map
        ]

        # Permission defaults follow the selected role.
        # Only privileged admins (MD/superuser) may override these flags.
        selected_role = None
        try:
            selected_role = (
                self.data.get("role") or self.initial.get("role") or ""
            ).strip()
        except Exception:
            selected_role = None

        defaults = ROLE_DEFAULTS.get(
            selected_role or "data_entry", ROLE_DEFAULTS["data_entry"]
        )
        self.fields["perm_manage_users"].initial = defaults.get("manage_users", False)
        self.fields["perm_create_clients"].initial = defaults.get(
            "create_clients", False
        )
        self.fields["perm_create_quotations"].initial = defaults.get(
            "create_quotations", False
        )
        self.fields["perm_create_invoices"].initial = defaults.get(
            "create_invoices", False
        )
        self.fields["perm_create_receipts"].initial = defaults.get(
            "create_receipts", False
        )
        self.fields["perm_access_reports"].initial = defaults.get(
            "access_reports", False
        )
        self.fields["perm_view_revenue"].initial = defaults.get("view_revenue", False)
        self.fields["perm_approve_verify"].initial = defaults.get(
            "approve_verify_receipts", False
        )
        self.fields["perm_void_unvoid"].initial = defaults.get(
            "void_unvoid_receipts", False
        )

        if not can_configure_permissions:
            for name in (
                "perm_manage_users",
                "perm_create_clients",
                "perm_create_quotations",
                "perm_create_invoices",
                "perm_create_receipts",
                "perm_access_reports",
                "perm_view_revenue",
                "perm_approve_verify",
                "perm_void_unvoid",
            ):
                self.fields[name].disabled = True

    def clean_role(self):
        role = self.cleaned_data.get("role")
        # choices are already filtered in __init__, but enforce on POST too.
        allowed = {key for key, _ in self.fields["role"].choices}
        if role not in allowed:
            raise forms.ValidationError(
                "You are not allowed to create a user with this role."
            )
        return role

    def save(self, commit=True):
        user = super().save(commit=False)

        # Store per-user permission overrides (only for non-privileged accounts).
        role = getattr(user, "role", None)
        if role not in {"superuser", "managing_director"}:
            user.permission_overrides = {
                "manage_users": bool(self.cleaned_data.get("perm_manage_users")),
                "create_clients": bool(self.cleaned_data.get("perm_create_clients")),
                "create_quotations": bool(
                    self.cleaned_data.get("perm_create_quotations")
                ),
                "create_invoices": bool(self.cleaned_data.get("perm_create_invoices")),
                "create_receipts": bool(self.cleaned_data.get("perm_create_receipts")),
                "access_reports": bool(self.cleaned_data.get("perm_access_reports")),
                "view_revenue": bool(self.cleaned_data.get("perm_view_revenue")),
                "approve_verify_receipts": bool(
                    self.cleaned_data.get("perm_approve_verify")
                ),
                "void_unvoid_receipts": bool(self.cleaned_data.get("perm_void_unvoid")),
            }
        else:
            user.permission_overrides = {}

        if commit:
            user.save()
        return user


class UserRoleUpdateForm(forms.Form):
    role = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        request_user = kwargs.pop("request_user", None)
        target_user = kwargs.pop("target_user", None)
        super().__init__(*args, **kwargs)

        creator_role = getattr(request_user, "role", None)
        is_super = bool(getattr(request_user, "is_superuser", False))

        if is_super:
            allowed = ["managing_director", "manager", "accountant", "data_entry"]
        elif creator_role == "managing_director":
            allowed = ["managing_director", "manager", "accountant", "data_entry"]
        else:
            allowed = []

        role_map = dict(CustomUser.ROLE_CHOICES)
        # Never allow selecting 'superuser' via this form (it is controlled by is_superuser).
        allowed = [key for key in allowed if key != "superuser"]
        self.fields["role"].choices = [
            (key, role_map[key]) for key in allowed if key in role_map
        ]

        if target_user is not None:
            self.fields["role"].initial = getattr(target_user, "role", None)

    def clean_role(self):
        role = self.cleaned_data.get("role")
        allowed = {key for key, _ in self.fields["role"].choices}
        if role not in allowed:
            raise forms.ValidationError("You are not allowed to assign this role.")
        return role


class UserDetailsUpdateForm(forms.ModelForm):
    """Edit core user profile fields (not role/permissions)."""

    class Meta:
        model = CustomUser
        fields = ["username", "email", "first_name", "last_name", "phone", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class UserPermissionOverridesForm(forms.Form):
    manage_users = forms.BooleanField(
        required=False,
        label="Can manage users",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_manage_users"}
        ),
    )
    create_clients = forms.BooleanField(
        required=False,
        label="Can create clients",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_clients"}
        ),
    )
    create_quotations = forms.BooleanField(
        required=False,
        label="Can create quotations",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_quotations"}
        ),
    )
    create_invoices = forms.BooleanField(
        required=False,
        label="Can create invoices",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_invoices"}
        ),
    )
    create_receipts = forms.BooleanField(
        required=False,
        label="Can record receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_create_receipts"}
        ),
    )
    access_reports = forms.BooleanField(
        required=False,
        label="Can access reports dashboard",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_access_reports"}
        ),
    )
    view_revenue = forms.BooleanField(
        required=False,
        label="Can view revenue totals",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_view_revenue"}
        ),
    )
    approve_verify_receipts = forms.BooleanField(
        required=False,
        label="Can approve/verify receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_approve_verify"}
        ),
    )
    void_unvoid_receipts = forms.BooleanField(
        required=False,
        label="Can void/unvoid receipts",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "perm_void_unvoid"}
        ),
    )

    def __init__(self, *args, user: CustomUser | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            effective = get_app_permissions(user)
            for field_name in self.fields:
                self.fields[field_name].initial = bool(effective.get(field_name, False))


class ClientForm(forms.ModelForm):
    """Form for creating and updating clients"""

    class Meta:
        model = Client
        fields = (
            "name",
            "company_name",
            "contact_person",
            "phone",
            "email",
            "country",
            "address",
            "remarks",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Client Name",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "company_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Company (if applicable)",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "contact_person": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Contact Person",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Phone Number"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "Email Address"}
            ),
            "country": forms.Select(attrs={"class": "form-control"}),
            "address": forms.Textarea(
                attrs={"class": "form-control", "placeholder": "Address", "rows": 3}
            ),
            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Remarks (optional)",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["remarks"].required = False


class LoadingForm(forms.ModelForm):
    """Form for creating and updating loadings"""

    class Meta:
        model = Loading
        fields = (
            "flow_type",
            "cargo_type",
            "client",
            "loading_date",
            "item_number",
            "item_description",
            "ctns",
            "weight",
            "gross_weight",
            "cargo_unit",
            "air_rate_basis",
            "rate_per_kg",
            "handling_fees",
            "airline",
            "payment_terms",
            "currency",
            "incoterm",
            "port_of_loading",
            "port_of_discharge",
            "final_destination",
            "vessel_voyage",
            "etd",
            "eta",
            "seal_number",
            "no_of_packages",
            "measurement",
            "awb_number",
            "flight_date",
            "estimated_arrival",
            "chargeable_weight",
            "commodity",
            "container_number",
            "container_size",
            "origin",
            "destination",
        )
        labels = {
            "cargo_type": "Cargo Type",
            "ctns": "Package Count",
            "weight": "CBM",
            "gross_weight": "Gross Weight (KGS)",
            "cargo_unit": "Package Type",
            "air_rate_basis": "Rate Basis",
            "rate_per_kg": "Rate",
            "handling_fees": "Handling Fees",
            "etd": "ETD (Estimated)",
            "eta": "ETA (Estimated)",
            "awb_number": "AWB No.",
            "estimated_arrival": "Estimated Arrival",
            "chargeable_weight": "Chargeable Weight",
        }
        widgets = {
            "flow_type": forms.Select(attrs={"class": "form-control"}),
            "cargo_type": forms.Select(attrs={"class": "form-control"}),
            "client": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-filterable": "1",
                    "data-filter-min": "1",
                    "data-filter-placeholder": "Search client (type to filter)",
                }
            ),
            "loading_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "item_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Item Number",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "item_description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Item Description",
                    "rows": 3,
                }
            ),
            "ctns": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Package count",
                    "min": "0",
                }
            ),
            "weight": _decimal_text_widget(placeholder="CBM"),
            "gross_weight": _decimal_text_widget(placeholder="Gross weight in KGS"),
            "cargo_unit": forms.Select(attrs={"class": "form-control"}),
            "air_rate_basis": forms.Select(attrs={"class": "form-control"}),
            "rate_per_kg": _decimal_text_widget(placeholder="Rate amount"),
            "handling_fees": _decimal_text_widget(
                placeholder="Handling fees (optional)"
            ),
            "airline": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Airline (optional)",
                    "autocapitalize": "words",
                    "data-smart-titlecase": "1",
                }
            ),
            "payment_terms": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "100% Before Shipment"}
            ),
            "currency": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "USD"}
            ),
            "incoterm": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "FOB Guangzhou, China"}
            ),
            "port_of_loading": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Port of loading"}
            ),
            "port_of_discharge": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Port of discharge"}
            ),
            "final_destination": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Final destination"}
            ),
            "vessel_voyage": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Vessel / voyage"}
            ),
            "etd": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "eta": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "seal_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Seal no."}
            ),
            "no_of_packages": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "No. of packages"}
            ),
            "measurement": _decimal_text_widget(placeholder="Measurement / CBM"),
            "awb_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "AWB no."}
            ),
            "flight_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "estimated_arrival": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "chargeable_weight": _decimal_text_widget(
                placeholder="Chargeable weight (kg)"
            ),
            "commodity": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Commodity"}
            ),
            "container_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Container Number",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "container_size": forms.Select(attrs={"class": "form-control"}),
            "origin": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Origin",
                    "autocapitalize": "sentences",
                    "data-smart-sentencecase": "1",
                }
            ),
            "destination": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Destination",
                    "autocapitalize": "sentences",
                    "data-smart-sentencecase": "1",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.order_by("name")
        self.fields["item_description"].required = False
        self.fields["client"].label_from_instance = (
            lambda c: f"{c.client_id} - {c.name}"
        )
        self.fields["item_number"].required = False
        self.fields["item_description"].required = False
        self.fields["ctns"].required = False
        self.fields["weight"].required = False
        self.fields["weight"].label = "CBM"
        self.fields["flow_type"].required = False
        self.fields["gross_weight"].required = False
        self.fields["air_rate_basis"].required = False
        self.fields["rate_per_kg"].required = False
        self.fields["handling_fees"].required = False
        self.fields["airline"].required = False
        self.fields["container_number"].required = False
        self.fields["container_size"].required = False
        self.fields["origin"].required = False
        self.fields["client"].empty_label = "Select client"
        flow_choices = [
            choice for choice in self.fields["flow_type"].choices if choice[0]
        ]
        self.fields["flow_type"].choices = [("", "Select flow type")] + flow_choices
        cargo_choices = [
            choice for choice in self.fields["cargo_type"].choices if choice[0]
        ]
        self.fields["cargo_type"].choices = [("", "Select cargo type")] + cargo_choices
        size_choices = [
            choice for choice in self.fields["container_size"].choices if choice[0]
        ]
        self.fields["container_size"].choices = [
            ("", "Select size (optional)")
        ] + size_choices

    def clean(self):
        cleaned = super().clean()
        flow_type = cleaned.get("flow_type")
        cargo_type = cleaned.get("cargo_type")
        weight = cleaned.get("weight")
        item_number = cleaned.get("item_number")
        ctns = cleaned.get("ctns")
        gross_weight = cleaned.get("gross_weight")
        rate_per_kg = cleaned.get("rate_per_kg")
        container_number = cleaned.get("container_number")
        container_size = cleaned.get("container_size")

        if cargo_type == "air_cargo":
            cleaned["flow_type"] = "lcl"
            cleaned["weight"] = None
            cleaned["container_number"] = ""
            cleaned["container_size"] = ""
            self.instance.weight = None
            self.instance.container_number = ""
            self.instance.container_size = ""
            self.instance.size_per_carton = ""
            if not (item_number or "").strip():
                self.add_error("item_number", "Item number is required for Air Cargo.")
            if ctns is None:
                self.add_error("ctns", "Package count is required for Air Cargo.")
            if gross_weight in (None, ""):
                self.add_error(
                    "gross_weight", "Gross weight in KGS is required for Air Cargo."
                )
            if rate_per_kg is None:
                self.add_error("rate_per_kg", "Rate is required for Air Cargo.")
            return cleaned

        if cargo_type == "freight_cargo":
            if not flow_type:
                self.add_error(
                    "flow_type", "Business flow is required for Freight Cargo."
                )
            cleaned["item_number"] = ""
            cleaned["rate_per_kg"] = None
            cleaned["air_rate_basis"] = "package"
            cleaned["handling_fees"] = 0
            cleaned["airline"] = ""
            cleaned["gross_weight"] = None
            cleaned["seal_number"] = ""
            cleaned["no_of_packages"] = ""
            cleaned["commodity"] = ""
            cleaned["origin"] = ""
            self.instance.item_number = ""
            self.instance.rate_per_kg = None
            self.instance.air_rate_basis = "package"
            self.instance.handling_fees = 0
            self.instance.airline = ""
            self.instance.size_per_carton = ""
            self.instance.gross_weight = None
            self.instance.seal_number = ""
            self.instance.no_of_packages = ""
            self.instance.commodity = ""
            self.instance.origin = ""
            if not (container_number or "").strip():
                self.add_error(
                    "container_number",
                    "Container number is required for Freight Cargo.",
                )
        if flow_type == "lcl":
            if weight in (None, ""):
                self.add_error("weight", "CBM is required for LCL shipments.")
        elif flow_type == "fcl":
            # Full container shipments do not capture CBM/tonnage.
            cleaned["weight"] = None
            if not container_size:
                self.add_error(
                    "container_size", "Container size is required for FCL shipments."
                )

        return cleaned


class TransitForm(forms.ModelForm):
    """Form for creating and updating transits"""

    class Meta:
        model = Transit
        fields = (
            "shipping_line",
            "container_number",
            "boarding_date",
            "eta_location",
            "eta",
            "status",
            "remarks",
        )
        widgets = {
            "shipping_line": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Shipping Line",
                    "style": "text-transform: capitalize;",
                    "autocapitalize": "words",
                    "data-smart-titlecase": "1",
                }
            ),
            "container_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Container Number",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "boarding_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "eta_location": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
            "eta": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "status": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Remarks (optional)",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shipping_line"].required = True
        self.fields["container_number"].required = True
        self.fields["eta_location"].required = True
        self.fields["eta"].required = True
        self.fields["remarks"].required = False


class PaymentForm(forms.ModelForm):
    """Form for creating and updating payments"""

    class Meta:
        model = Payment
        fields = (
            "loading",
            "rate_per_cbm",
            "rate_per_container",
            "document_handling_fee",
            "pvoc_fee",
            "payment_date",
            "payment_method",
            "receipt_number",
        )
        widgets = {
            "loading": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-filterable": "1",
                    "data-filter-min": "1",
                    "data-filter-placeholder": "Search cargo / client / reference (type to filter)",
                }
            ),
            "rate_per_cbm": _decimal_text_widget(placeholder="Rate per CBM (for LCL)"),
            "rate_per_container": _decimal_text_widget(
                placeholder="Rate per Container (for FCL)"
            ),
            "document_handling_fee": _decimal_text_widget(
                placeholder="Document & Handling Fees (optional)"
            ),
            "pvoc_fee": _decimal_text_widget(placeholder="PVOC Fee (optional)"),
            "payment_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "receipt_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Receipt Number (optional)",
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()
        loading = cleaned.get("loading")
        rate_per_cbm = cleaned.get("rate_per_cbm")
        rate_per_container = cleaned.get("rate_per_container")
        document_handling_fee = cleaned.get("document_handling_fee") or 0
        pvoc_fee = cleaned.get("pvoc_fee") or 0

        if not loading:
            return cleaned

        if getattr(loading, "cargo_type", None) == "air_cargo":
            air_total = loading.air_cargo_total
            if air_total is None:
                self.add_error(
                    "loading",
                    "Selected Air Cargo is missing qty or rate. Update the cargo record first.",
                )
                return cleaned
            cleaned["rate_per_cbm"] = None
            cleaned["rate_per_container"] = None
            cleaned["document_handling_fee"] = loading.handling_fees or 0
            cleaned["pvoc_fee"] = 0
            self.instance.rate_per_cbm = None
            self.instance.rate_per_container = None
            self.instance.document_handling_fee = loading.handling_fees or 0
            self.instance.pvoc_fee = 0
            self.instance.amount_charged = air_total
            return cleaned

        flow_type = getattr(loading, "flow_type", None)
        if flow_type == "lcl":
            # Ensure we don't accidentally keep an FCL rate.
            cleaned["rate_per_container"] = None
            self.instance.rate_per_container = None
            if loading.weight is None:
                self.add_error(
                    "loading",
                    "Selected cargo is LCL but CBM is missing. Update the cargo record first.",
                )
                return cleaned
            if rate_per_cbm is None:
                self.add_error(
                    "rate_per_cbm", "Rate per CBM is required for LCL invoices."
                )
                return cleaned
            self.instance.amount_charged = (
                (loading.weight * rate_per_cbm)
                + document_handling_fee
                + (loading.weight * pvoc_fee)
            )
        elif flow_type == "fcl":
            # Ensure we don't accidentally keep an LCL rate.
            cleaned["rate_per_cbm"] = None
            self.instance.rate_per_cbm = None
            if rate_per_container is None:
                self.add_error(
                    "rate_per_container",
                    "Rate per container is required for FCL invoices.",
                )
                return cleaned
            self.instance.amount_charged = (
                rate_per_container + document_handling_fee + pvoc_fee
            )
        else:
            self.add_error(
                "loading",
                "Selected cargo does not have a flow type set. Update the cargo record first.",
            )

        return cleaned


class PaymentTransactionForm(forms.ModelForm):
    """Form for recording individual payment events"""

    class Meta:
        model = PaymentTransaction
        fields = ("amount", "payment_date", "payment_method", "reference", "notes")
        widgets = {
            "amount": _decimal_text_widget(placeholder="Amount Received"),
            "payment_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "reference": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Transaction ID / Reference",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Optional notes",
                    "rows": 3,
                }
            ),
        }


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = [
            "client",
            "cargo_type",
            "flow_type",
            "origin",
            "destination",
            "loading_date",
            "item_number",
            "item_description",
            "ctns",
            "gross_weight",
            "cargo_unit",
            "air_rate_basis",
            "rate_per_kg",
            "handling_fees",
            "airline",
            "payment_terms",
            "currency",
            "awb_number",
            "flight_date",
            "estimated_arrival",
            "commodity",
            "cbm",
            "rate_per_cbm",
            "rate_per_container",
            "document_handling_fee",
            "status",
            "notes",
        ]
        widgets = {
            "client": forms.Select(
                attrs={
                    "class": "form-select",
                    "data-filterable": "1",
                    "data-filter-min": "1",
                    "data-filter-placeholder": "Search client (type to filter)",
                }
            ),
            "cargo_type": forms.Select(attrs={"class": "form-select"}),
            "flow_type": forms.Select(attrs={"class": "form-select"}),
            "origin": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. UAE - Dubai",
                    "autocapitalize": "sentences",
                    "data-smart-sentencecase": "1",
                }
            ),
            "destination": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Kampala",
                    "autocapitalize": "sentences",
                    "data-smart-sentencecase": "1",
                }
            ),
            "loading_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "item_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Air cargo item number",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "item_description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Optional cargo description",
                }
            ),
            "ctns": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Package count",
                    "min": "0",
                }
            ),
            "gross_weight": _decimal_text_widget(placeholder="Gross weight in KGS"),
            "cargo_unit": forms.Select(attrs={"class": "form-select"}),
            "air_rate_basis": forms.Select(attrs={"class": "form-select"}),
            "rate_per_kg": _decimal_text_widget(placeholder="Rate amount"),
            "handling_fees": _decimal_text_widget(
                placeholder="Air cargo handling fees (optional)"
            ),
            "airline": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Airline (optional)",
                    "autocapitalize": "words",
                    "data-smart-titlecase": "1",
                }
            ),
            "payment_terms": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "100% Before Shipment"}
            ),
            "currency": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "USD"}
            ),
            "awb_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "AWB no."}
            ),
            "flight_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "estimated_arrival": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "commodity": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Commodity"}
            ),
            "cbm": _decimal_text_widget(placeholder="Client CBM (LCL only)"),
            "rate_per_cbm": _decimal_text_widget(placeholder="e.g. 120"),
            "rate_per_container": _decimal_text_widget(placeholder="e.g. 2500"),
            "document_handling_fee": _decimal_text_widget(placeholder="e.g. 50"),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional notes to the client",
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        cargo_type = cleaned.get("cargo_type")
        flow_type = cleaned.get("flow_type")
        origin = cleaned.get("origin")
        destination = cleaned.get("destination")
        loading_date = cleaned.get("loading_date")
        item_number = cleaned.get("item_number")
        item_description = cleaned.get("item_description")
        ctns = cleaned.get("ctns")
        gross_weight = cleaned.get("gross_weight")
        rate_per_kg = cleaned.get("rate_per_kg")
        cbm = cleaned.get("cbm")
        container_size = cleaned.get("container_size")
        rate_per_cbm = cleaned.get("rate_per_cbm")
        rate_per_container = cleaned.get("rate_per_container")
        document_handling_fee = cleaned.get("document_handling_fee") or 0

        cleaned["document_handling_fee"] = document_handling_fee
        cleaned["pvoc_fee"] = 0
        self.instance.document_handling_fee = document_handling_fee
        self.instance.pvoc_fee = 0

        if not client:
            self.add_error("client", "Client is required.")
        if not cargo_type:
            self.add_error("cargo_type", "Cargo type is required.")
        if cargo_type == "air_cargo":
            cleaned["flow_type"] = "lcl"
            cleaned["container_number"] = ""
            cleaned["container_size"] = ""
            cleaned["cbm"] = None
            cleaned["rate_per_cbm"] = None
            cleaned["rate_per_container"] = None
            cleaned["document_handling_fee"] = 0
            cleaned["pvoc_fee"] = 0
            self.instance.flow_type = "lcl"
            self.instance.container_number = ""
            self.instance.container_size = ""
            self.instance.cbm = None
            self.instance.rate_per_cbm = None
            self.instance.rate_per_container = None
            self.instance.document_handling_fee = 0
            self.instance.pvoc_fee = 0
            self.instance.size_per_carton = ""
        elif flow_type == "lcl":
            cleaned["item_number"] = ""
            cleaned["ctns"] = None
            cleaned["rate_per_kg"] = None
            cleaned["air_rate_basis"] = "package"
            cleaned["handling_fees"] = 0
            cleaned["airline"] = ""
            cleaned["gross_weight"] = None
            cleaned["commodity"] = ""
            self.instance.item_number = ""
            self.instance.ctns = None
            self.instance.rate_per_kg = None
            self.instance.air_rate_basis = "package"
            self.instance.handling_fees = 0
            self.instance.airline = ""
            self.instance.size_per_carton = ""
            self.instance.gross_weight = None
            self.instance.commodity = ""
            self.instance.pvoc_fee = 0
        elif flow_type == "fcl":
            cleaned["item_number"] = ""
            cleaned["ctns"] = None
            cleaned["rate_per_kg"] = None
            cleaned["air_rate_basis"] = "package"
            cleaned["handling_fees"] = 0
            cleaned["airline"] = ""
            cleaned["gross_weight"] = None
            cleaned["commodity"] = ""
            self.instance.item_number = ""
            self.instance.ctns = None
            self.instance.rate_per_kg = None
            self.instance.air_rate_basis = "package"
            self.instance.handling_fees = 0
            self.instance.airline = ""
            self.instance.size_per_carton = ""
            self.instance.gross_weight = None
            self.instance.commodity = ""
            self.instance.pvoc_fee = 0
        elif cargo_type == "freight_cargo":
            self.add_error("flow_type", "Flow type is required for freight quotations.")

        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.order_by("name")
        self.fields["client"].label_from_instance = (
            lambda c: f"{c.client_id} - {c.name}"
        )
        cargo_choices = [
            choice for choice in self.fields["cargo_type"].choices if choice[0]
        ]
        self.fields["cargo_type"].choices = [("", "Select cargo type")] + cargo_choices


class QuoteInvoiceConversionForm(forms.Form):
    """Quotation updates and invoice-stage details captured during conversion."""

    loading_date = forms.DateTimeField(
        required=True,
        label="Expected Loading Date",
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"}
        ),
    )
    destination = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Destination"}
        ),
    )
    item_number = forms.CharField(
        required=False,
        label="Item Number",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Item number",
                "style": "text-transform: uppercase;",
                "autocapitalize": "characters",
            }
        ),
    )
    item_description = forms.CharField(
        required=False,
        label="Description",
        widget=forms.Textarea(
            attrs={"class": "form-control", "placeholder": "Description", "rows": 2}
        ),
    )
    origin = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Origin"}
        ),
    )
    ctns = forms.IntegerField(
        required=False,
        label="Package Count",
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Package count", "min": "0"}
        ),
    )
    gross_weight = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        label="Gross Weight (KGS)",
        widget=_decimal_text_widget(placeholder="Gross weight in KGS"),
    )
    cargo_unit = forms.ChoiceField(
        required=False,
        label="Package Type",
        choices=Loading.CARGO_UNIT_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    air_rate_basis = forms.ChoiceField(
        required=False,
        label="Rate Basis",
        choices=Loading.AIR_RATE_BASIS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    rate_per_kg = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        label="Rate",
        widget=_decimal_text_widget(placeholder="Rate amount"),
    )
    handling_fees = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        label="Handling Fees",
        widget=_decimal_text_widget(placeholder="Handling fees"),
    )
    airline = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Airline"}
        ),
    )

    container_number = forms.CharField(
        required=False,
        label="Container No.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Container number or TBC",
                "style": "text-transform: uppercase;",
                "autocapitalize": "characters",
                "autocomplete": "off",
            }
        ),
    )
    container_size = forms.ChoiceField(
        required=False,
        label="Container Type",
        choices=[("", "Select container type")]
        + list(Loading._meta.get_field("container_size").choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    port_of_loading = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Port of loading"}
        ),
    )
    port_of_discharge = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Port of discharge"}
        ),
    )
    final_destination = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Final destination"}
        ),
    )
    vessel_voyage = forms.CharField(
        required=False,
        label="Vessel / Voyage",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Vessel / voyage"}
        ),
    )
    etd = forms.DateTimeField(
        required=False,
        label="ETD (Estimated)",
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"}
        ),
    )
    eta = forms.DateTimeField(
        required=False,
        label="ETA (Estimated)",
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"}
        ),
    )
    measurement = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=_decimal_text_widget(placeholder="Measurement / CBM"),
    )
    incoterm = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Incoterm"}
        ),
    )
    rate_per_cbm = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=_decimal_text_widget(placeholder="Rate per CBM"),
    )
    rate_per_container = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=_decimal_text_widget(placeholder="Rate per container"),
    )
    document_handling_fee = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=_decimal_text_widget(placeholder="Document & handling fee"),
    )
    pvoc_fee = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=_decimal_text_widget(placeholder="PVOC fee"),
    )

    def __init__(self, *args, quote=None, **kwargs):
        self.quote = quote
        initial = kwargs.setdefault("initial", {})
        if quote is not None:
            initial.setdefault("loading_date", quote.loading_date)
            initial.setdefault("destination", quote.destination or "")
            initial.setdefault("item_number", quote.item_number or "")
            initial.setdefault("item_description", quote.item_description or "")
            initial.setdefault("origin", quote.origin or "")
            initial.setdefault("ctns", quote.ctns)
            initial.setdefault("gross_weight", quote.gross_weight)
            initial.setdefault("cargo_unit", quote.cargo_unit or "ctn")
            initial.setdefault("air_rate_basis", quote.air_rate_basis or "package")
            initial.setdefault("rate_per_kg", quote.rate_per_kg)
            initial.setdefault("handling_fees", quote.handling_fees or 0)
            initial.setdefault("airline", quote.airline or "")
            initial.setdefault("final_destination", quote.destination or "")
            initial.setdefault("measurement", quote.cbm)
            initial.setdefault("rate_per_cbm", quote.rate_per_cbm)
            initial.setdefault("rate_per_container", quote.rate_per_container)
            initial.setdefault(
                "document_handling_fee", quote.document_handling_fee or 0
            )
            initial.setdefault("pvoc_fee", 0)
        super().__init__(*args, **kwargs)

        if getattr(quote, "cargo_type", None) == "air_cargo":
            for field_name in [
                "container_number",
                "container_size",
                "port_of_loading",
                "port_of_discharge",
                "final_destination",
                "vessel_voyage",
                "etd",
                "eta",
                "measurement",
                "incoterm",
                "rate_per_cbm",
                "rate_per_container",
                "pvoc_fee",
            ]:
                self.fields[field_name].disabled = True
        else:
            for field_name in [
                "item_number",
                "item_description",
                "ctns",
                "gross_weight",
                "cargo_unit",
                "air_rate_basis",
                "rate_per_kg",
                "handling_fees",
                "airline",
            ]:
                self.fields[field_name].disabled = True

    def clean(self):
        cleaned = super().clean()
        quote = self.quote
        if quote is None:
            return cleaned

        if quote.cargo_type == "air_cargo":
            if not (cleaned.get("origin") or "").strip():
                self.add_error("origin", "Origin is required for Air Cargo.")
            if not (cleaned.get("item_number") or "").strip():
                self.add_error("item_number", "Item number is required for Air Cargo.")
            if cleaned.get("ctns") is None:
                self.add_error("ctns", "Package count is required for Air Cargo.")
            if cleaned.get("gross_weight") is None:
                self.add_error(
                    "gross_weight", "Gross weight in KGS is required for Air Cargo."
                )
            if cleaned.get("rate_per_kg") is None:
                self.add_error("rate_per_kg", "Rate is required for Air Cargo.")
            cleaned["handling_fees"] = cleaned.get("handling_fees") or 0
            cleaned["document_handling_fee"] = cleaned.get("document_handling_fee") or 0
            cleaned["pvoc_fee"] = 0
            return cleaned

        if not (cleaned.get("port_of_loading") or "").strip():
            self.add_error("port_of_loading", "Port of loading is required.")
        if not (cleaned.get("port_of_discharge") or "").strip():
            self.add_error("port_of_discharge", "Port of discharge is required.")
        if not (cleaned.get("final_destination") or quote.destination or "").strip():
            self.add_error("final_destination", "Final destination is required.")
        if quote.flow_type == "lcl":
            if cleaned.get("measurement") is None and quote.cbm is None:
                self.add_error(
                    "measurement", "Measurement / CBM is required for LCL invoices."
                )
            if cleaned.get("rate_per_cbm") is None:
                self.add_error(
                    "rate_per_cbm", "Rate per CBM is required for LCL invoices."
                )
        elif quote.flow_type == "fcl":
            if not cleaned.get("container_size"):
                self.add_error(
                    "container_size", "Container type is required for FCL invoices."
                )
            if not (cleaned.get("container_number") or "").strip():
                self.add_error(
                    "container_number", "Container number is required for FCL invoices."
                )
            if cleaned.get("rate_per_container") is None:
                self.add_error(
                    "rate_per_container",
                    "Rate per container is required for FCL invoices.",
                )

        cleaned["document_handling_fee"] = cleaned.get("document_handling_fee") or 0
        cleaned["pvoc_fee"] = cleaned.get("pvoc_fee") or 0
        return cleaned


class ContainerReturnForm(forms.ModelForm):
    """Form for creating and updating container returns"""

    class Meta:
        model = ContainerReturn
        fields = (
            "container_number",
            "container_size",
            "loading",
            "return_date",
            "condition",
            "status",
            "remarks",
        )
        widgets = {
            "container_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Container Number",
                    "style": "text-transform: uppercase;",
                    "autocapitalize": "characters",
                    "autocomplete": "off",
                }
            ),
            "container_size": forms.Select(attrs={"class": "form-control"}),
            "loading": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-filterable": "1",
                    "data-filter-min": "1",
                    "data-filter-placeholder": "Search cargo / client / container (type to filter)",
                }
            ),
            "return_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "condition": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Remarks (optional)",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loading"].queryset = Loading.objects.select_related(
            "client"
        ).order_by("-created_at")
        self.fields["loading"].label_from_instance = (
            lambda l: f"{l.container_number} - {l.client.client_id} - {l.client.name}"
        )


class SendDocumentEmailForm(forms.Form):
    to_email = forms.EmailField(
        label="Recipient Email",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "client@example.com"}
        ),
    )
    subject = forms.CharField(
        label="Subject",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    message = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
    )
