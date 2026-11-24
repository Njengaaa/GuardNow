from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-2fa/', views.verify_two_factor, name='verify_two_factor'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='core/password_reset.html',
        email_template_name='core/password_reset_email.txt',
        subject_template_name='core/password_reset_subject.txt',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('client/', views.client_dashboard, name='client_dashboard'),
    path('client/profile/', views.profile, name='profile'),
    path('client/requests/new/', views.create_request, name='create_request'),
    path('admin-panel/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-panel/requests/<int:request_id>/status/', views.update_request_status, name='update_request_status'),
    path('admin-panel/requests/<int:request_id>/assign/', views.assign_guard, name='assign_guard'),
    path('admin-panel/assignments/', views.assignment_list, name='assignment_list'),
    path('admin-panel/assignments/<int:assignment_id>/attendance/', views.record_attendance, name='record_attendance'),
    path('admin-panel/payments/', views.payments, name='payments'),
    path('admin-panel/invoices/', views.invoices, name='invoices'),
    path('admin-panel/requests/<int:request_id>/invoice/', views.create_invoice, name='create_invoice'),
    path('admin-panel/invoices/<int:invoice_id>/status/', views.update_invoice_status, name='update_invoice_status'),
    path('admin-panel/rewards/new/', views.create_reward, name='create_reward'),
    path('admin-panel/payments/<int:payment_id>/status/', views.update_payment_status, name='update_payment_status'),
    path('admin-panel/reports/', views.reports, name='reports'),
    path('admin-panel/reports/export.csv', views.reports_csv, name='reports_csv'),
    path('admin-panel/audit/', views.audit_log, name='audit_log'),
    path('manual/', views.user_manual, name='user_manual'),
]
