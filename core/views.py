from functools import wraps
import csv
import secrets
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    AssignmentForm,
    AttendanceForm,
    ClientRegistrationForm,
    EmailAuthenticationForm,
    GuardRequestForm,
    PaymentPeriodForm,
    PaymentStatusForm,
    RewardForm,
)
from .models import AuditLog, Assignment, Guard, GuardRequest, Invoice, Payment, Reward, ShiftLog, User


def record_audit(request, action, details='', user=None):
    audit_user = user
    if audit_user is None:
        candidate = getattr(request, 'user', None)
        if candidate is not None and candidate.is_authenticated:
            audit_user = candidate
    AuditLog.objects.create(
        user=audit_user,
        action=action,
        details=details,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def role_required(role):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role != role:
                messages.error(request, 'You do not have permission to view that page.')
                return redirect(
                    'admin_dashboard'
                    if request.user.role == User.Role.ADMIN
                    else 'client_dashboard'
                )
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = ClientRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Your client account is ready.')
        return redirect('client_dashboard')
    return render(request, 'core/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        code = f'{secrets.randbelow(1000000):06d}'
        request.session['pending_2fa_user_id'] = user.pk
        request.session['pending_2fa_code'] = code
        request.session['pending_2fa_expires'] = (
            timezone.now() + timedelta(minutes=10)
        ).isoformat()
        send_mail(
            'Your GuardLink verification code',
            f'Your login verification code is {code}. It expires in 10 minutes.',
            None,
            [user.email],
            fail_silently=False,
        )
        record_audit(request, 'Login verification requested', f'Email: {user.email}', user)
        return redirect('verify_two_factor')
    return render(request, 'core/login.html', {'form': form})


def verify_two_factor(request):
    if request.method == 'POST':
        submitted_code = request.POST.get('code', '').strip()
        user_id = request.session.get('pending_2fa_user_id')
        expected_code = request.session.get('pending_2fa_code')
        expires_at = request.session.get('pending_2fa_expires')
        try:
            expired = datetime.fromisoformat(expires_at) < timezone.now()
        except (TypeError, ValueError):
            expired = True
        if (
            not expired
            and submitted_code
            and secrets.compare_digest(submitted_code, expected_code or '')
            and user_id
        ):
            user = get_object_or_404(User, pk=user_id)
            login(request, user)
            for key in ('pending_2fa_user_id', 'pending_2fa_code', 'pending_2fa_expires'):
                request.session.pop(key, None)
            record_audit(request, 'Login successful', f'Email: {user.email}', user)
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('admin_dashboard' if user.role == User.Role.ADMIN else 'client_dashboard')
        messages.error(request, 'The verification code is invalid or has expired.')
    return render(request, 'core/two_factor_verify.html')


@login_required
@require_POST
def logout_view(request):
    record_audit(request, 'Logout', f'Email: {request.user.email}')
    logout(request)
    return redirect('home')


@login_required
def dashboard(request):
    if request.user.role == User.Role.ADMIN:
        return redirect('admin_dashboard')
    return redirect('client_dashboard')


@role_required(User.Role.CLIENT)
def client_dashboard(request):
    requests = GuardRequest.objects.filter(client=request.user).select_related('site', 'rank')
    invoices = Invoice.objects.filter(
        request__client=request.user,
        status__in=[Invoice.Status.ISSUED, Invoice.Status.PAID],
    ).select_related('request__site', 'request__shift')
    return render(request, 'core/client_dashboard.html', {'requests': requests, 'invoices': invoices})


@role_required(User.Role.CLIENT)
def create_request(request):
    form = GuardRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(request.user)
        messages.success(request, 'Your guard request has been submitted for review.')
        return redirect('client_dashboard')
    return render(request, 'core/request_form.html', {'form': form})


@role_required(User.Role.CLIENT)
def profile(request):
    if request.method == 'POST':
        request.user.full_name = request.POST.get('full_name', '').strip()
        request.user.phone = request.POST.get('phone', '').strip()
        if not request.user.full_name:
            messages.error(request, 'Name cannot be empty.')
        else:
            request.user.save(update_fields=['full_name', 'phone'])
            messages.success(request, 'Your profile has been updated.')
            return redirect('client_dashboard')
    return render(request, 'core/profile.html')


@role_required(User.Role.ADMIN)
def admin_dashboard(request):
    requests = GuardRequest.objects.select_related(
        'client',
        'site',
        'rank',
        'shift',
    ).prefetch_related('assignments__guard')
    assignments = Assignment.objects.select_related('guard', 'shift', 'request__site')[:10]
    return render(request, 'core/admin_dashboard.html', {
        'requests': requests,
        'assignments': assignments,
        'available_guards': Guard.objects.filter(status=Guard.Status.AVAILABLE).count(),
        'pending_requests': GuardRequest.objects.filter(status=GuardRequest.Status.PENDING).count(),
        'payment_count': Payment.objects.count(),
        'invoice_count': Invoice.objects.count(),
    })


@role_required(User.Role.ADMIN)
@require_POST
def update_request_status(request, request_id):
    service_request = get_object_or_404(GuardRequest, pk=request_id)
    new_status = request.POST.get('status')
    valid_statuses = {
        GuardRequest.Status.APPROVED,
        GuardRequest.Status.REJECTED,
        GuardRequest.Status.COMPLETED,
    }
    if new_status not in valid_statuses:
        messages.error(request, 'That request status is not valid.')
    elif new_status == GuardRequest.Status.COMPLETED and not service_request.assignments.exists():
        messages.error(request, 'Assign at least one guard before completing this request.')
    else:
        service_request.status = new_status
        service_request.save(update_fields=['status'])
        record_audit(request, 'Guard request status changed', f'Request #{service_request.pk}: {new_status}')
        messages.success(request, f'Request #{service_request.pk} marked {service_request.get_status_display().lower()}.')
    return redirect('admin_dashboard')


@role_required(User.Role.ADMIN)
def assign_guard(request, request_id):
    service_request = get_object_or_404(GuardRequest, pk=request_id)
    if service_request.status != GuardRequest.Status.APPROVED:
        messages.error(request, 'Approve the request before assigning guards.')
        return redirect('admin_dashboard')
    assigned_count = service_request.assignments.count()
    if assigned_count >= service_request.guards_needed:
        messages.error(request, 'All requested guard positions have already been assigned.')
        return redirect('admin_dashboard')
    form = AssignmentForm(service_request, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
        record_audit(request, 'Guard assigned', f'Request #{service_request.pk}; guard #{form.cleaned_data["guard"].pk}')
        messages.success(request, 'Guard assigned successfully.')
        if service_request.assignments.count() >= service_request.guards_needed:
            return redirect('admin_dashboard')
        return redirect('assign_guard', request_id=service_request.pk)
    return render(request, 'core/assign_guard.html', {
        'form': form,
        'service_request': service_request,
        'assigned_count': assigned_count,
    })


@role_required(User.Role.ADMIN)
def assignment_list(request):
    assignments = Assignment.objects.select_related('request__site', 'guard', 'shift')
    return render(request, 'core/assignments.html', {'assignments': assignments})


@role_required(User.Role.ADMIN)
def record_attendance(request, assignment_id):
    assignment = get_object_or_404(
        Assignment.objects.select_related('guard', 'shift', 'request'),
        pk=assignment_id,
    )
    form = AttendanceForm(request.POST or None)
    if request.method == 'POST':
        form.instance.assignment = assignment
        if form.is_valid():
            log, created = ShiftLog.objects.update_or_create(
                assignment=assignment,
                work_date=form.cleaned_data['work_date'],
                defaults={'attendance': form.cleaned_data['attendance']},
            )
            record_audit(request, 'Attendance recorded', f'Assignment #{assignment.pk}; {form.cleaned_data["work_date"]}; {form.cleaned_data["attendance"]}')
            messages.success(request, 'Attendance recorded.' if created else 'Attendance updated.')
            return redirect('assignment_list')
    return render(request, 'core/attendance_form.html', {'form': form, 'assignment': assignment})


@role_required(User.Role.ADMIN)
def payments(request):
    form = PaymentPeriodForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        payment, _ = Payment.objects.get_or_create(
            guard=data['guard'],
            period_start=data['period_start'],
            period_end=data['period_end'],
        )
        payment.recalculate()
        record_audit(request, 'Payment recalculated', f'Guard #{payment.guard.pk}; {payment.period_start} to {payment.period_end}')
        messages.success(request, f'Payment calculated. Total: {payment.total_amount:.2f}.')
        return redirect('payments')
    return render(request, 'core/payments.html', {
        'form': form,
        'payments': Payment.objects.select_related('guard', 'guard__rank'),
        'rewards': Reward.objects.select_related('guard'),
    })


@role_required(User.Role.ADMIN)
def create_reward(request):
    form = RewardForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reward = form.save()
        matching_payment = Payment.objects.filter(
            guard=reward.guard,
            period_start__lte=reward.date_awarded,
            period_end__gte=reward.date_awarded,
        ).order_by('-period_end').first()
        if matching_payment:
            reward.payment = matching_payment
            reward.save(update_fields=['payment'])
            matching_payment.recalculate()
        messages.success(request, 'Reward recorded.')
        return redirect('payments')
    return render(request, 'core/reward_form.html', {'form': form})


@role_required(User.Role.ADMIN)
@require_POST
def update_payment_status(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id)
    form = PaymentStatusForm(request.POST, instance=payment)
    if form.is_valid():
        form.save()
        record_audit(request, 'Payment status changed', f'Payment #{payment.pk}: {payment.status}')
        messages.success(request, 'Payment status updated.')
    else:
        messages.error(request, 'Could not update payment status.')
    return redirect('payments')


@role_required(User.Role.ADMIN)
def invoices(request):
    return render(request, 'core/invoices.html', {
        'invoices': Invoice.objects.select_related('request__client', 'request__site', 'request__shift'),
        'billable_requests': GuardRequest.objects.filter(
            status__in=[GuardRequest.Status.APPROVED, GuardRequest.Status.COMPLETED],
            invoice__isnull=True,
        ).select_related('client', 'site', 'rank', 'shift').prefetch_related('assignments'),
    })


@role_required(User.Role.ADMIN)
@require_POST
def create_invoice(request, request_id):
    service_request = get_object_or_404(
        GuardRequest,
        pk=request_id,
        status__in=[GuardRequest.Status.APPROVED, GuardRequest.Status.COMPLETED],
    )
    if service_request.assignments.count() != service_request.guards_needed:
        messages.error(request, 'Assign all requested guards before creating an invoice.')
        return redirect('invoices')
    invoice, created = Invoice.objects.get_or_create(request=service_request)
    if created:
        invoice.recalculate()
        record_audit(request, 'Invoice created', f'Invoice #{invoice.pk}; request #{service_request.pk}')
        messages.success(request, f'Draft invoice created for {invoice.guard_days} scheduled guard-days.')
    else:
        messages.error(request, 'An invoice already exists for this request.')
    return redirect('invoices')


@role_required(User.Role.ADMIN)
@require_POST
def update_invoice_status(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    new_status = request.POST.get('status')
    if invoice.status == Invoice.Status.DRAFT and new_status == Invoice.Status.ISSUED:
        invoice.status = Invoice.Status.ISSUED
        invoice.save(update_fields=['status'])
        record_audit(request, 'Invoice issued', f'Invoice #{invoice.pk}')
        messages.success(request, 'Invoice issued and made visible to the client.')
    elif invoice.status == Invoice.Status.ISSUED and new_status == Invoice.Status.PAID:
        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=['status'])
        record_audit(request, 'Invoice paid', f'Invoice #{invoice.pk}')
        messages.success(request, 'Invoice marked as paid.')
    else:
        messages.error(request, 'That invoice status change is not allowed.')
    return redirect('invoices')


@role_required(User.Role.ADMIN)
def reports(request):
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    status = request.GET.get('status', '')
    invoices = Invoice.objects.select_related(
        'request__client', 'request__site', 'request__shift'
    )
    if start_date:
        invoices = invoices.filter(created_at__date__gte=start_date)
    if end_date:
        invoices = invoices.filter(created_at__date__lte=end_date)
    if status:
        invoices = invoices.filter(status=status)
    payments = Payment.objects.select_related('guard', 'guard__rank')
    if start_date:
        payments = payments.filter(period_start__gte=start_date)
    if end_date:
        payments = payments.filter(period_end__lte=end_date)
    return render(request, 'core/reports.html', {
        'invoices': invoices,
        'payments': payments,
        'start_date': start_date or '',
        'end_date': end_date or '',
        'status': status,
    })


@role_required(User.Role.ADMIN)
def reports_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="guardlink_invoices.csv"'
    writer = csv.writer(response)
    writer.writerow(['Invoice', 'Client', 'Site', 'Status', 'Guard-days', 'Rate', 'Total', 'Created'])
    for invoice in Invoice.objects.select_related('request__client', 'request__site'):
        writer.writerow([
            invoice.pk,
            invoice.request.client.full_name,
            invoice.request.site.site_name,
            invoice.status,
            invoice.guard_days,
            invoice.client_daily_rate,
            invoice.total_amount,
            invoice.created_at.date(),
        ])
    return response


@role_required(User.Role.ADMIN)
def audit_log(request):
    return render(request, 'core/audit_log.html', {
        'logs': AuditLog.objects.select_related('user')[:500],
    })


def user_manual(request):
    return render(request, 'core/user_manual.html')
