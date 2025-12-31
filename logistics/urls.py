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
    
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Users
    path('users/', views.user_list, name='user_list'),
    
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
    path('transits/create/<int:loading_id>/', views.transit_create, name='transit_create_with_loading'),
    path('transits/<int:pk>/update/', views.transit_update, name='transit_update'),
    
    # Payments
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/create/', views.payment_create, name='payment_create'),
    path('payments/create/<int:loading_id>/', views.payment_create, name='payment_create_with_loading'),
    path('payments/<int:pk>/', views.payment_detail, name='payment_detail'),
    path('payments/<int:pk>/update/', views.payment_update, name='payment_update'),
    path('payments/<int:pk>/invoice/', views.payment_invoice, name='payment_invoice'),
    path(
        'payments/transactions/<int:transaction_id>/receipt/',
        views.payment_receipt,
        name='payment_receipt',
    ),
    
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
    path('export/containers/', views.export_containers_csv, name='export_containers_csv'),
    path('export/containers/pdf/', views.export_containers_pdf, name='export_containers_pdf'),
    
    # Audit Logs
    path('audit-logs/', views.audit_log_view, name='audit_logs'),
]
