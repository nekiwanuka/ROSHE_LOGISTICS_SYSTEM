"""
Django forms for the logistics management system
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Client, Loading, Transit, Payment, PaymentTransaction, ContainerReturn
from .models import Quote

from .permissions import ROLE_DEFAULTS, get_app_permissions


def _decimal_text_widget(*, css_class: str = 'form-control', placeholder: str = ''):
    """Prefer text inputs for decimals to avoid browser rounding/coercion from type=number."""
    attrs = {
        'class': css_class,
        'inputmode': 'decimal',
        'autocomplete': 'off',
        # Accept digits and a single decimal separator; keep it permissive for mobile keyboards.
        'pattern': r'[0-9]*[\.,]?[0-9]*',
    }
    if placeholder:
        attrs['placeholder'] = placeholder
    return forms.TextInput(attrs=attrs)


class UserRegistrationForm(UserCreationForm):
    """Form for creating new users"""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username'
        })
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email'
        })
    )
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'First Name'
        })
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Last Name'
        })
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Phone Number'
        })
    )
    role = forms.ChoiceField(
        choices=CustomUser.ROLE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )

    perm_manage_users = forms.BooleanField(
        required=False,
        label='Can manage users',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_manage_users'}),
    )

    perm_create_clients = forms.BooleanField(
        required=False,
        label='Can create clients',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_clients'}),
    )
    perm_create_quotations = forms.BooleanField(
        required=False,
        label='Can create quotations',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_quotations'}),
    )
    perm_create_invoices = forms.BooleanField(
        required=False,
        label='Can create invoices',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_invoices'}),
    )
    perm_create_receipts = forms.BooleanField(
        required=False,
        label='Can record receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_receipts'}),
    )
    perm_access_reports = forms.BooleanField(
        required=False,
        label='Can access reports/exports',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_access_reports'}),
    )

    perm_view_revenue = forms.BooleanField(
        required=False,
        label='Can view revenue totals',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_view_revenue'}),
    )
    perm_approve_verify = forms.BooleanField(
        required=False,
        label='Can approve/verify receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_approve_verify'}),
    )
    perm_void_unvoid = forms.BooleanField(
        required=False,
        label='Can void/unvoid receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_void_unvoid'}),
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        })
    )
    
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'first_name', 'last_name', 'phone', 'role')

    def __init__(self, *args, **kwargs):
        request_user = kwargs.pop('request_user', None)
        can_configure_permissions = bool(kwargs.pop('can_configure_permissions', False))
        super().__init__(*args, **kwargs)

        # Role assignment rules:
        # - Superuser: may create Managing Director, Manager, Accountant, Front Desk.
        # - Managing Director: may create Manager, Accountant, Front Desk.
        # - Manager: may create Accountant, Front Desk.
        # - Others: no user creation rights.
        creator_role = getattr(request_user, 'role', None)
        is_super = bool(getattr(request_user, 'is_superuser', False))

        if is_super:
            allowed = ['managing_director', 'manager', 'accountant', 'data_entry']
        elif creator_role == 'managing_director':
            allowed = ['manager', 'accountant', 'data_entry']
        elif creator_role == 'manager':
            allowed = ['accountant', 'data_entry']
        else:
            allowed = []

        # Never allow creating a superuser via the UI.
        role_map = dict(CustomUser.ROLE_CHOICES)
        self.fields['role'].choices = [(key, role_map[key]) for key in allowed if key in role_map]

        # Permission defaults follow the selected role.
        # Only privileged admins (MD/superuser) may override these flags.
        selected_role = None
        try:
            selected_role = (self.data.get('role') or self.initial.get('role') or '').strip()
        except Exception:
            selected_role = None

        defaults = ROLE_DEFAULTS.get(selected_role or 'data_entry', ROLE_DEFAULTS['data_entry'])
        self.fields['perm_manage_users'].initial = defaults.get('manage_users', False)
        self.fields['perm_create_clients'].initial = defaults.get('create_clients', False)
        self.fields['perm_create_quotations'].initial = defaults.get('create_quotations', False)
        self.fields['perm_create_invoices'].initial = defaults.get('create_invoices', False)
        self.fields['perm_create_receipts'].initial = defaults.get('create_receipts', False)
        self.fields['perm_access_reports'].initial = defaults.get('access_reports', False)
        self.fields['perm_view_revenue'].initial = defaults.get('view_revenue', False)
        self.fields['perm_approve_verify'].initial = defaults.get('approve_verify_receipts', False)
        self.fields['perm_void_unvoid'].initial = defaults.get('void_unvoid_receipts', False)

        if not can_configure_permissions:
            for name in (
                'perm_manage_users',
                'perm_create_clients',
                'perm_create_quotations',
                'perm_create_invoices',
                'perm_create_receipts',
                'perm_access_reports',
                'perm_view_revenue',
                'perm_approve_verify',
                'perm_void_unvoid',
            ):
                self.fields[name].disabled = True

    def clean_role(self):
        role = self.cleaned_data.get('role')
        # choices are already filtered in __init__, but enforce on POST too.
        allowed = {key for key, _ in self.fields['role'].choices}
        if role not in allowed:
            raise forms.ValidationError('You are not allowed to create a user with this role.')
        return role

    def save(self, commit=True):
        user = super().save(commit=False)

        # Store per-user permission overrides (only for non-privileged accounts).
        role = getattr(user, 'role', None)
        if role not in {'superuser', 'managing_director'}:
            user.permission_overrides = {
                'manage_users': bool(self.cleaned_data.get('perm_manage_users')),
                'create_clients': bool(self.cleaned_data.get('perm_create_clients')),
                'create_quotations': bool(self.cleaned_data.get('perm_create_quotations')),
                'create_invoices': bool(self.cleaned_data.get('perm_create_invoices')),
                'create_receipts': bool(self.cleaned_data.get('perm_create_receipts')),
                'access_reports': bool(self.cleaned_data.get('perm_access_reports')),
                'view_revenue': bool(self.cleaned_data.get('perm_view_revenue')),
                'approve_verify_receipts': bool(self.cleaned_data.get('perm_approve_verify')),
                'void_unvoid_receipts': bool(self.cleaned_data.get('perm_void_unvoid')),
            }
        else:
            user.permission_overrides = {}

        if commit:
            user.save()
        return user


class UserRoleUpdateForm(forms.Form):
    role = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        request_user = kwargs.pop('request_user', None)
        target_user = kwargs.pop('target_user', None)
        super().__init__(*args, **kwargs)

        creator_role = getattr(request_user, 'role', None)
        is_super = bool(getattr(request_user, 'is_superuser', False))

        if is_super:
            allowed = ['managing_director', 'manager', 'accountant', 'data_entry']
        elif creator_role == 'managing_director':
            allowed = ['managing_director', 'manager', 'accountant', 'data_entry']
        else:
            allowed = []

        role_map = dict(CustomUser.ROLE_CHOICES)
        # Never allow selecting 'superuser' via this form (it is controlled by is_superuser).
        allowed = [key for key in allowed if key != 'superuser']
        self.fields['role'].choices = [(key, role_map[key]) for key in allowed if key in role_map]

        if target_user is not None:
            self.fields['role'].initial = getattr(target_user, 'role', None)

    def clean_role(self):
        role = self.cleaned_data.get('role')
        allowed = {key for key, _ in self.fields['role'].choices}
        if role not in allowed:
            raise forms.ValidationError('You are not allowed to assign this role.')
        return role


class UserDetailsUpdateForm(forms.ModelForm):
    """Edit core user profile fields (not role/permissions)."""

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UserPermissionOverridesForm(forms.Form):
    manage_users = forms.BooleanField(
        required=False,
        label='Can manage users',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_manage_users'}),
    )
    create_clients = forms.BooleanField(
        required=False,
        label='Can create clients',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_clients'}),
    )
    create_quotations = forms.BooleanField(
        required=False,
        label='Can create quotations',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_quotations'}),
    )
    create_invoices = forms.BooleanField(
        required=False,
        label='Can create invoices',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_invoices'}),
    )
    create_receipts = forms.BooleanField(
        required=False,
        label='Can record receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_create_receipts'}),
    )
    access_reports = forms.BooleanField(
        required=False,
        label='Can access reports dashboard',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_access_reports'}),
    )
    view_revenue = forms.BooleanField(
        required=False,
        label='Can view revenue totals',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_view_revenue'}),
    )
    approve_verify_receipts = forms.BooleanField(
        required=False,
        label='Can approve/verify receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_approve_verify'}),
    )
    void_unvoid_receipts = forms.BooleanField(
        required=False,
        label='Can void/unvoid receipts',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'perm_void_unvoid'}),
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
            'name',
            'company_name',
            'contact_person',
            'phone',
            'email',
            'country',
            'address',
            'remarks',
        )
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Client Name',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Company (if applicable)',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact Person',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone Number'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email Address'
            }),
            'country': forms.Select(attrs={
                'class': 'form-control'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Address',
                'rows': 3
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Remarks (optional)',
                'rows': 3
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['remarks'].required = False


class LoadingForm(forms.ModelForm):
    """Form for creating and updating loadings"""
    
    class Meta:
        model = Loading
        fields = (
            'flow_type',
            'client',
            'loading_date',
            'item_description',
            'weight',
            'container_number',
            'container_size',
            'origin',
            'destination',
        )
        widgets = {
            'flow_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'client': forms.Select(
                attrs={
                    'class': 'form-control',
                    'data-filterable': '1',
                    'data-filter-min': '1',
                    'data-filter-placeholder': 'Search client (type to filter)'
                }
            ),
            'loading_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'item_description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Item Description',
                'rows': 3
            }),
            'weight': _decimal_text_widget(placeholder='CBM'),
            'container_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Container Number',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'container_size': forms.Select(attrs={
                'class': 'form-control'
            }),
            'origin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Origin',
                'autocapitalize': 'sentences',
                'data-smart-sentencecase': '1'
            }),
            'destination': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Destination',
                'autocapitalize': 'sentences',
                'data-smart-sentencecase': '1'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('name')
        self.fields['client'].label_from_instance = lambda c: f"{c.client_id} - {c.name}"
        self.fields['item_description'].required = False
        self.fields['weight'].required = False
        self.fields['weight'].label = 'CBM'
        self.fields['container_size'].required = False
        self.fields['client'].empty_label = 'Select client'
        flow_choices = [choice for choice in self.fields['flow_type'].choices if choice[0]]
        self.fields['flow_type'].choices = [('', 'Select flow type')] + flow_choices
        size_choices = [choice for choice in self.fields['container_size'].choices if choice[0]]
        self.fields['container_size'].choices = [('', 'Select size (optional)')] + size_choices

    def clean(self):
        cleaned = super().clean()
        flow_type = cleaned.get('flow_type')
        weight = cleaned.get('weight')
        container_size = cleaned.get('container_size')

        if flow_type == 'lcl':
            if weight in (None, ''):
                self.add_error('weight', 'CBM is required for LCL shipments.')
        elif flow_type == 'fcl':
            # Full container shipments do not capture CBM/tonnage.
            cleaned['weight'] = None
            if not container_size:
                self.add_error('container_size', 'Container size is required for FCL shipments.')

        return cleaned


class TransitForm(forms.ModelForm):
    """Form for creating and updating transits"""
    
    class Meta:
        model = Transit
        fields = (
            'shipping_line',
            'container_number',
            'boarding_date',
            'eta_location',
            'eta',
            'status',
            'remarks',
        )
        widgets = {
            'shipping_line': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Shipping Line',
                'style': 'text-transform: capitalize;',
                'autocapitalize': 'words',
                'data-smart-titlecase': '1'
            }),
            'container_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Container Number',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'boarding_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'eta_location': forms.Select(attrs={
                'class': 'form-control',
            }),
            'eta': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Remarks (optional)',
                'rows': 3
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shipping_line'].required = True
        self.fields['container_number'].required = True
        self.fields['eta_location'].required = True
        self.fields['eta'].required = True
        self.fields['remarks'].required = False


class PaymentForm(forms.ModelForm):
    """Form for creating and updating payments"""
    
    class Meta:
        model = Payment
        fields = (
            'loading',
            'rate_per_cbm',
            'rate_per_container',
            'document_handling_fee',
            'payment_date',
            'payment_method',
            'receipt_number',
        )
        widgets = {
            'loading': forms.Select(
                attrs={
                    'class': 'form-control',
                    'data-filterable': '1',
                    'data-filter-min': '1',
                    'data-filter-placeholder': 'Search cargo / client / container (type to filter)'
                }
            ),
            'rate_per_cbm': _decimal_text_widget(placeholder='Rate per CBM (for LCL)'),
            'rate_per_container': _decimal_text_widget(placeholder='Rate per Container (for FCL)'),
            'document_handling_fee': _decimal_text_widget(placeholder='Document & Handling Fees (optional)'),
            'payment_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-control'
            }),
            'receipt_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Receipt Number (optional)'
            }),
        }

    def clean(self):
        cleaned = super().clean()
        loading = cleaned.get('loading')
        rate_per_cbm = cleaned.get('rate_per_cbm')
        rate_per_container = cleaned.get('rate_per_container')
        document_handling_fee = cleaned.get('document_handling_fee') or 0

        if not loading:
            return cleaned

        flow_type = getattr(loading, 'flow_type', None)
        if flow_type == 'lcl':
            # Ensure we don't accidentally keep an FCL rate.
            cleaned['rate_per_container'] = None
            self.instance.rate_per_container = None
            if loading.weight is None:
                self.add_error('loading', 'Selected cargo is LCL but CBM is missing. Update the cargo record first.')
                return cleaned
            if rate_per_cbm is None:
                self.add_error('rate_per_cbm', 'Rate per CBM is required for LCL invoices.')
                return cleaned
            self.instance.amount_charged = (loading.weight * rate_per_cbm) + document_handling_fee
        elif flow_type == 'fcl':
            # Ensure we don't accidentally keep an LCL rate.
            cleaned['rate_per_cbm'] = None
            self.instance.rate_per_cbm = None
            if rate_per_container is None:
                self.add_error('rate_per_container', 'Rate per container is required for FCL invoices.')
                return cleaned
            self.instance.amount_charged = rate_per_container + document_handling_fee
        else:
            self.add_error('loading', 'Selected cargo does not have a flow type set. Update the cargo record first.')

        return cleaned


class PaymentTransactionForm(forms.ModelForm):
    """Form for recording individual payment events"""

    class Meta:
        model = PaymentTransaction
        fields = ('amount', 'payment_date', 'payment_method', 'reference', 'notes')
        widgets = {
            'amount': _decimal_text_widget(placeholder='Amount Received'),
            'payment_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-control'
            }),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction ID / Reference'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Optional notes',
                'rows': 3
            })
        }

class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = [
            'client',
            'flow_type',
            'container_number',
            'container_size',
            'origin',
            'destination',
            'loading_date',
            'item_description',
            'cbm',
            'rate_per_cbm',
            'rate_per_container',
            'document_handling_fee',
            'status',
            'notes',
        ]
        widgets = {
            'client': forms.Select(
                attrs={
                    'class': 'form-select',
                    'data-filterable': '1',
                    'data-filter-min': '1',
                    'data-filter-placeholder': 'Search client (type to filter)'
                }
            ),
            'flow_type': forms.Select(attrs={'class': 'form-select'}),
            'container_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. MSCU1234567',
                    'style': 'text-transform: uppercase;',
                    'autocapitalize': 'characters',
                    'autocomplete': 'off',
                }
            ),
            'container_size': forms.Select(attrs={'class': 'form-select'}),
            'origin': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. UAE - Dubai',
                    'autocapitalize': 'sentences',
                    'data-smart-sentencecase': '1',
                }
            ),
            'destination': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. Kampala',
                    'autocapitalize': 'sentences',
                    'data-smart-sentencecase': '1',
                }
            ),
            'loading_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'item_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional cargo description'}),
            'cbm': _decimal_text_widget(placeholder='Client CBM (LCL only)'),
            'rate_per_cbm': _decimal_text_widget(placeholder='e.g. 120'),
            'rate_per_container': _decimal_text_widget(placeholder='e.g. 2500'),
            'document_handling_fee': _decimal_text_widget(placeholder='e.g. 50'),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional notes to the client'}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get('client')
        flow_type = cleaned.get('flow_type')
        container_number = cleaned.get('container_number')
        origin = cleaned.get('origin')
        destination = cleaned.get('destination')
        loading_date = cleaned.get('loading_date')
        cbm = cleaned.get('cbm')
        container_size = cleaned.get('container_size')
        rate_per_cbm = cleaned.get('rate_per_cbm')
        rate_per_container = cleaned.get('rate_per_container')

        if not client:
            self.add_error('client', 'Client is required.')
        if not container_number:
            self.add_error('container_number', 'Container number is required.')
        if not origin:
            self.add_error('origin', 'Origin is required.')
        if not destination:
            self.add_error('destination', 'Destination is required.')
        if not loading_date:
            self.add_error('loading_date', 'Loading date is required.')

        if flow_type == 'lcl':
            if cbm is None:
                self.add_error('cbm', 'CBM is required for LCL quotations (provided by the client).')
            if not rate_per_cbm:
                self.add_error('rate_per_cbm', 'Cost per CBM is required for LCL quotations.')
        elif flow_type == 'fcl':
            if not container_size:
                self.add_error('container_size', 'Container size is required for FCL quotations.')
            if not rate_per_container:
                self.add_error('rate_per_container', 'Cost per container is required for FCL quotations.')

        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('name')
        self.fields['client'].label_from_instance = lambda c: f"{c.client_id} - {c.name}"


class ContainerReturnForm(forms.ModelForm):
    """Form for creating and updating container returns"""
    
    class Meta:
        model = ContainerReturn
        fields = (
            'container_number',
            'container_size',
            'loading',
            'return_date',
            'condition',
            'status',
            'remarks',
        )
        widgets = {
            'container_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Container Number',
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off'
            }),
            'container_size': forms.Select(attrs={
                'class': 'form-control'
            }),
            'loading': forms.Select(
                attrs={
                    'class': 'form-control',
                    'data-filterable': '1',
                    'data-filter-min': '1',
                    'data-filter-placeholder': 'Search cargo / client / container (type to filter)'
                }
            ),
            'return_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'condition': forms.Select(attrs={
                'class': 'form-control'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Remarks (optional)',
                'rows': 3
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['loading'].queryset = Loading.objects.select_related('client').order_by('-created_at')
        self.fields['loading'].label_from_instance = (
            lambda l: f"{l.container_number} - {l.client.client_id} - {l.client.name}"
        )

class SendDocumentEmailForm(forms.Form):
    to_email = forms.EmailField(
        label='Recipient Email',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'client@example.com'}),
    )
    subject = forms.CharField(
        label='Subject',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    message = forms.CharField(
        label='Message',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
    )
