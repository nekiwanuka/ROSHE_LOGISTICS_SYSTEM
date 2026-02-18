"""
URL configuration for the logistics app
"""
from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('integrations/whatsapp/webhook/', views.whatsapp_webhook, name='whatsapp_webhook'),
    
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('search/', views.global_search, name='global_search'),
    path('dashboard/reset-seed/', views.dashboard_reset_keep_users_and_seed, name='dashboard_reset_seed'),
    
    # Users
    path('users/', views.user_list, name='user_list'),
    path('users/<int:pk>/permissions/', views.user_permissions_update, name='user_permissions_update'),
    path('users/<int:pk>/edit/', views.user_update_details, name='user_update_details'),
    path('users/<int:pk>/password/', views.user_change_password, name='user_change_password'),
    path('users/<int:pk>/role/', views.user_role_update, name='user_role_update'),
    path('users/<int:pk>/login-as/', views.user_login_as, name='user_login_as'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    
    # Clients
    path('clients/', views.client_list, name='client_list'),
    path('clients/create/', views.client_create, name='client_create'),
    path('clients/<int:pk>/', views.client_detail, name='client_detail'),
    path('clients/<int:pk>/update/', views.client_update, name='client_update'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    
    # Loadings
    path('loadings/', views.loading_list, name='loading_list'),
    path('loadings/create/', views.loading_create, name='loading_create'),
    path('loadings/<int:pk>/', views.loading_detail, name='loading_detail'),
    path('loadings/<int:pk>/update/', views.loading_update, name='loading_update'),
    path('loadings/<int:pk>/delete/', views.loading_delete, name='loading_delete'),
    
    # Transits
    path('transits/', views.transit_list, name='transit_list'),
    path('transits/create/', views.transit_create, name='transit_create'),
    path('transits/<int:pk>/update/', views.transit_update, name='transit_update'),
    
    # Payments
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/create/', views.payment_create, name='payment_create'),
    path('payments/create/<int:loading_id>/', views.payment_create, name='payment_create_with_loading'),
    path('payments/<int:pk>/', views.payment_detail, name='payment_detail'),
    path('payments/<int:pk>/update/', views.payment_update, name='payment_update'),
    path('payments/<int:pk>/delete/', views.payment_delete, name='payment_delete'),
    path('payments/<int:pk>/invoice/', views.payment_invoice, name='payment_invoice'),
    path('payments/<int:pk>/invoice/email/', views.payment_invoice_email, name='payment_invoice_email'),
    path('payments/<int:pk>/invoice/whatsapp/', views.payment_invoice_whatsapp, name='payment_invoice_whatsapp'),
    path(
        'payments/transactions/<int:transaction_id>/receipt/',
        views.payment_receipt,
        name='payment_receipt',
    ),
    path(
        'payments/transactions/<int:transaction_id>/receipt/email/',
        views.payment_receipt_email,
        name='payment_receipt_email',
    ),
    path(
        'payments/transactions/<int:transaction_id>/receipt/whatsapp/',
        views.payment_receipt_whatsapp,
        name='payment_receipt_whatsapp',
    ),

        # Quotations
        path('quotations/', views.quote_list, name='quote_list'),
        path('quotations/create/', views.quote_create, name='quote_create'),
        path('quotations/<int:quote_id>/', views.quote_detail, name='quote_detail'),
        path('quotations/<int:quote_id>/pdf/', views.quote_pdf, name='quote_pdf'),
        path('quotations/<int:quote_id>/edit/', views.quote_update, name='quote_update'),
        path('quotations/<int:quote_id>/delete/', views.quote_delete, name='quote_delete'),
        path('quotations/<int:quote_id>/convert/', views.quote_convert_to_invoice, name='quote_convert_to_invoice'),

        # Receipts
        path('receipts/', views.receipt_list, name='receipt_list'),
        path('receipts/<int:transaction_id>/void/', views.receipt_void, name='receipt_void'),
        path('receipts/<int:transaction_id>/unvoid/', views.receipt_unvoid, name='receipt_unvoid'),
    
    # Container Returns
    path('containers/', views.container_return_list, name='container_return_list'),
    path('containers/create/', views.container_return_create, name='container_return_create'),
    path('containers/<int:pk>/update/', views.container_return_update, name='container_return_update'),
    
    # Reports & Exports
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('export/clients/', views.export_clients_csv, name='export_clients_csv'),
    path('export/clients/pdf/', views.export_clients_pdf, name='export_clients_pdf'),
    path('export/shipments/', views.export_shipments_csv, name='export_shipments_csv'),
    path('export/shipments/pdf/', views.export_shipments_pdf, name='export_shipments_pdf'),
    path('export/payments/', views.export_payments_csv, name='export_payments_csv'),
    path('export/payments/pdf/', views.export_payments_pdf, name='export_payments_pdf'),
    path('export/receipts/', views.export_receipts_csv, name='export_receipts_csv'),
    path('export/receipts/pdf/', views.export_receipts_pdf, name='export_receipts_pdf'),
    path('export/containers/', views.export_containers_csv, name='export_containers_csv'),
    path('export/containers/pdf/', views.export_containers_pdf, name='export_containers_pdf'),
    path('export/quotations/', views.export_quotes_csv, name='export_quotes_csv'),
    path('export/quotations/pdf/', views.export_quotes_pdf, name='export_quotes_pdf'),
    
    # Audit Logs
    path('audit-logs/', views.audit_log_view, name='audit_logs'),
]
