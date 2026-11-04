from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
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
]
