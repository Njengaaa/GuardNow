from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
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
from .models import Assignment, Guard, GuardRequest, Invoice, Payment, Reward, ShiftLog, User


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
        login(request, form.get_user())
        next_url = request.POST.get('next') or request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(
            'admin_dashboard'
            if form.get_user().role == User.Role.ADMIN
            else 'client_dashboard'
        )
    return render(request, 'core/login.html', {'form': form})


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
        messages.success(request, 'Invoice issued and made visible to the client.')
    elif invoice.status == Invoice.Status.ISSUED and new_status == Invoice.Status.PAID:
        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=['status'])
        messages.success(request, 'Invoice marked as paid.')
    else:
        messages.error(request, 'That invoice status change is not allowed.')
    return redirect('invoices')
