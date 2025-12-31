"""
Django forms for the logistics management system
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Client, Loading, Transit, Payment, PaymentTransaction, ContainerReturn


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
                'placeholder': 'Client Name'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Company (if applicable)'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact Person'
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
            'loading_id',
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
            'loading_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Loading ID'
            }),
            'client': forms.Select(attrs={
                'class': 'form-control'
            }),
            'loading_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'item_description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Item Description',
                'rows': 3
            }),
            'weight': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Weight (KG)',
                'step': '0.01'
            }),
            'container_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Container Number'
            }),
            'container_size': forms.Select(attrs={
                'class': 'form-control'
            }),
            'origin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Origin'
            }),
            'destination': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Destination'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['weight'].required = False
        self.fields['container_size'].required = False
        self.fields['client'].empty_label = 'Select client'
        size_choices = [choice for choice in self.fields['container_size'].choices if choice[0]]
        self.fields['container_size'].choices = [('', 'Select size (optional)')] + size_choices


class TransitForm(forms.ModelForm):
    """Form for creating and updating transits"""
    
    class Meta:
        model = Transit
        fields = ('loading', 'vessel_name', 'boarding_date', 'eta_kampala', 'status', 'remarks')
        widgets = {
            'loading': forms.Select(attrs={
                'class': 'form-control'
            }),
            'vessel_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Vessel Name'
            }),
            'boarding_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'eta_kampala': forms.DateTimeInput(attrs={
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
        self.fields['remarks'].required = False


class PaymentForm(forms.ModelForm):
    """Form for creating and updating payments"""
    
    class Meta:
        model = Payment
        fields = ('loading', 'amount_charged', 'payment_date', 
                  'payment_method', 'receipt_number')
        widgets = {
            'loading': forms.Select(attrs={
                'class': 'form-control'
            }),
            'amount_charged': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Amount Charged',
                'step': '0.01'
            }),
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


class PaymentTransactionForm(forms.ModelForm):
    """Form for recording individual payment events"""

    class Meta:
        model = PaymentTransaction
        fields = ('amount', 'payment_date', 'payment_method', 'reference', 'notes')
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Amount Received',
                'step': '0.01'
            }),
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
                'placeholder': 'Container Number'
            }),
            'container_size': forms.Select(attrs={
                'class': 'form-control'
            }),
            'loading': forms.Select(attrs={
                'class': 'form-control'
            }),
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
        self.fields['container_size'].required = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['remarks'].required = False
