from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('An email address is required.')
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.ADMIN)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('A superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise Valu
            eError('A superuser must have is_superuser=True.')
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        CLIENT = 'client', 'Client'
        ADMIN = 'admin', 'Administrator'

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CLIENT)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
    objects = UserManager()

    def __str__(self):
        return self.full_name or self.email


class Rank(models.Model):
    name = models.CharField(max_length=50, unique=True)
    guard_daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    client_daily_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['name']
        constraints = [
            models.CheckConstraint(condition=Q(guard_daily_rate__gt=0), name='rank_guard_rate_positive'),
            models.CheckConstraint(condition=Q(client_daily_rate__gt=0), name='rank_client_rate_positive'),
        ]

    def __str__(self):
        return self.name


class Site(models.Model):
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sites')
    site_name = models.CharField(max_length=100)
    address = models.CharField(max_length=150)
    county = models.CharField(max_length=50)

    class Meta:
        ordering = ['site_name']
        constraints = [
            models.UniqueConstraint(fields=['client', 'site_name'], name='unique_client_site_name'),
        ]

    def __str__(self):
        return f'{self.site_name} ({self.county})'


class Guard(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        DEPLOYED = 'deployed', 'Deployed'
        ON_LEAVE = 'on_leave', 'On leave'

    full_name = models.CharField(max_length=100)
    national_id = models.CharField(max_length=30, unique=True)
    phone = models.CharField(max_length=20)
    rank = models.ForeignKey(Rank, on_delete=models.PROTECT, related_name='guards')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)
    date_hired = models.DateField()

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} — {self.rank.name}'


class GuardRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        COMPLETED = 'completed', 'Completed'

    client = models.ForeignKey(User, on_delete=models.PROTECT, related_name='guard_requests')
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='guard_requests')
    rank = models.ForeignKey(Rank, on_delete=models.PROTECT, related_name='guard_requests')
    shift = models.ForeignKey(
        'Shift',
        on_delete=models.PROTECT,
        related_name='guard_requests',
        null=True,
        blank=True,
    )
    guards_needed = models.PositiveIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(guards_needed__gt=0), name='request_guard_count_positive'),
            models.CheckConstraint(condition=Q(end_date__gte=models.F('start_date')), name='request_end_after_start'),
        ]

    def __str__(self):
        return f'Request #{self.pk} — {self.site.site_name}'


class Shift(models.Model):
    name = models.CharField(max_length=30, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return self.name


class Assignment(models.Model):
    request = models.ForeignKey(GuardRequest, on_delete=models.PROTECT, related_name='assignments')
    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name='assignments')
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name='assignments')
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ['start_date', 'guard__full_name']
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F('start_date')), name='assignment_end_after_start'),
        ]

    def clean(self):
        errors = {}
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors['end_date'] = 'End date must be on or after the start date.'
        if self.request_id and self.start_date and self.end_date:
            service_request = self.request
            if service_request.status != GuardRequest.Status.APPROVED:
                errors['request'] = 'Only approved requests can have guard assignments.'
            if self.guard_id and self.guard.rank_id != service_request.rank_id:
                errors['guard'] = 'The guard rank must match the requested rank.'
            if self.guard_id and self.guard.status == Guard.Status.ON_LEAVE:
                errors['guard'] = 'A guard on leave cannot be assigned.'
            if service_request.shift_id and self.shift_id != service_request.shift_id:
                errors['shift'] = 'The assigned shift must match the shift requested by the client.'
            if service_request.assignments.exclude(pk=self.pk).count() >= service_request.guards_needed:
                errors['request'] = 'The request already has all required guard assignments.'
            if self.start_date < service_request.start_date or self.end_date > service_request.end_date:
                errors['start_date'] = 'Assignment dates must fall within the client request dates.'
        if self.guard_id and self.shift_id and self.start_date and self.end_date:
            others = Assignment.objects.filter(
                guard_id=self.guard_id,
                start_date__lte=self.end_date + timedelta(days=1),
                end_date__gte=self.start_date - timedelta(days=1),
            ).exclude(pk=self.pk).select_related('shift')
            start_minute = self.shift.start_time.hour * 60 + self.shift.start_time.minute
            end_minute = self.shift.end_time.hour * 60 + self.shift.end_time.minute
            if end_minute <= start_minute:
                end_minute += 24 * 60
            for other in others:
                other_start = other.shift.start_time.hour * 60 + other.shift.start_time.minute
                other_end = other.shift.end_time.hour * 60 + other.shift.end_time.minute
                if other_end <= other_start:
                    other_end += 24 * 60
                for day_offset in (-1, 0, 1):
                    shared_days = (
                        max(self.start_date, other.start_date - timedelta(days=day_offset))
                        <= min(self.end_date, other.end_date - timedelta(days=day_offset))
                    )
                    other_shift_start = other_start + day_offset * 24 * 60
                    other_shift_end = other_end + day_offset * 24 * 60
                    if shared_days and start_minute < other_shift_end and other_shift_start < end_minute:
                        errors['guard'] = 'This guard already has an assignment that overlaps this shift.'
                        break
                if errors.get('guard'):
                    break
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.guard} — {self.shift} ({self.start_date} to {self.end_date})'


class ShiftLog(models.Model):
    class Attendance(models.TextChoices):
        PRESENT = 'present', 'Present'
        ABSENT = 'absent', 'Absent'
        LATE = 'late', 'Late'

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='shift_logs')
    work_date = models.DateField()
    attendance = models.CharField(max_length=10, choices=Attendance.choices)

    class Meta:
        ordering = ['-work_date']
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'work_date'], name='unique_assignment_attendance_date'),
        ]

    def clean(self):
        if self.assignment_id and self.work_date:
            if not self.assignment.start_date <= self.work_date <= self.assignment.end_date:
                raise ValidationError({'work_date': 'Attendance date must fall within the assignment dates.'})

    def __str__(self):
        return f'{self.assignment.guard} — {self.work_date}: {self.get_attendance_display()}'


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name='payments')
    period_start = models.DateField()
    period_end = models.DateField()
    shifts_worked = models.PositiveIntegerField(default=0)
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    bonus_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ['-period_end', 'guard__full_name']
        constraints = [
            models.UniqueConstraint(fields=['guard', 'period_start', 'period_end'], name='unique_guard_payment_period'),
            models.CheckConstraint(condition=Q(period_end__gte=models.F('period_start')), name='payment_end_after_start'),
        ]

    def clean(self):
        if self.guard_id and self.period_start and self.period_end and self.period_end >= self.period_start:
            overlapping_periods = Payment.objects.filter(
                guard_id=self.guard_id,
                period_start__lte=self.period_end,
                period_end__gte=self.period_start,
            ).exclude(pk=self.pk)
            if overlapping_periods.exists():
                raise ValidationError({
                    'period_start': 'This period overlaps another payment period for the same guard.',
                })

    def has_perfect_attendance(self):
        assignments = list(Assignment.objects.filter(
            guard=self.guard,
            start_date__lte=self.period_end,
            end_date__gte=self.period_start,
        ))
        scheduled_shift_days = sum(
            (min(assignment.end_date, self.period_end) - max(assignment.start_date, self.period_start)).days + 1
            for assignment in assignments
        )
        if not scheduled_shift_days:
            return False
        present_shift_days = ShiftLog.objects.filter(
            assignment__in=assignments,
            work_date__range=(self.period_start, self.period_end),
            attendance=ShiftLog.Attendance.PRESENT,
        ).count()
        return present_shift_days == scheduled_shift_days

    def recalculate(self):
        present_logs = ShiftLog.objects.filter(
            assignment__guard=self.guard,
            work_date__range=(self.period_start, self.period_end),
            attendance=ShiftLog.Attendance.PRESENT,
        )
        self.shifts_worked = present_logs.count()
        self.base_amount = self.guard.rank.guard_daily_rate * self.shifts_worked
        period_rewards = list(Reward.objects.filter(
            guard=self.guard,
            date_awarded__range=(self.period_start, self.period_end),
        ).filter(Q(payment=self) | Q(payment__isnull=True)))
        qualified_rewards = [
            reward for reward in period_rewards
            if reward.reason != Reward.Reason.PERFECT_ATTENDANCE or self.has_perfect_attendance()
        ]
        percentage_rewards = [reward for reward in qualified_rewards if reward.percentage is not None]
        legacy_rewards = [reward for reward in period_rewards if reward.percentage is None]
        highest_percentage_reward = max(
            percentage_rewards,
            key=lambda reward: reward.percentage,
            default=None,
        )
        percentage_bonus = Decimal('0.00')
        if highest_percentage_reward:
            percentage_bonus = (
                self.base_amount * highest_percentage_reward.percentage / Decimal('100')
            ).quantize(Decimal('0.01'))
        legacy_bonus = sum((reward.amount for reward in legacy_rewards), Decimal('0.00'))
        self.bonus_amount = percentage_bonus + legacy_bonus
        self.total_amount = self.base_amount + self.bonus_amount
        self.save(update_fields=['shifts_worked', 'base_amount', 'bonus_amount', 'total_amount'])
        for reward in period_rewards:
            reward.payment = self
            if reward.percentage is not None:
                reward.amount = (
                    percentage_bonus
                    if reward == highest_percentage_reward
                    else Decimal('0.00')
                )
        if period_rewards:
            Reward.objects.bulk_update(period_rewards, ['payment', 'amount'])

    def __str__(self):
        return f'{self.guard} — {self.period_start} to {self.period_end}'


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ISSUED = 'issued', 'Issued'
        PAID = 'paid', 'Paid'

    request = models.OneToOneField(
        GuardRequest,
        on_delete=models.PROTECT,
        related_name='invoice',
    )
    guard_days = models.PositiveIntegerField(default=0)
    client_daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gte=0), name='invoice_total_nonnegative'),
        ]

    def recalculate(self):
        if self.status != self.Status.DRAFT:
            raise ValidationError('Only draft invoices can be recalculated.')
        assignments = self.request.assignments.all()
        if assignments.count() != self.request.guards_needed:
            raise ValidationError('Assign all requested guards before creating the invoice.')
        self.guard_days = sum(
            (assignment.end_date - assignment.start_date).days + 1
            for assignment in assignments
        )
        self.client_daily_rate = self.request.rank.client_daily_rate
        self.total_amount = self.guard_days * self.client_daily_rate
        self.save(update_fields=['guard_days', 'client_daily_rate', 'total_amount'])

    def __str__(self):
        return f'Invoice for request #{self.request_id} — {self.total_amount}'


class Reward(models.Model):
    class Reason(models.TextChoices):
        EXCELLENT_SERVICE = 'Excellent Service', 'Excellent Service (25%)'
        GOOD_SERVICE = 'Good Service', 'Good Service (5%)'
        PERFECT_ATTENDANCE = 'Perfect Attendance', 'Perfect Attendance (10%)'
        CLIENT_PERFECT_RATING = 'Client Perfect Rating', 'Client Perfect Rating (5%)'

    PERCENTAGES = {
        Reason.EXCELLENT_SERVICE: Decimal('25.00'),
        Reason.GOOD_SERVICE: Decimal('5.00'),
        Reason.PERFECT_ATTENDANCE: Decimal('10.00'),
        Reason.CLIENT_PERFECT_RATING: Decimal('5.00'),
        'Excellent service': Decimal('25.00'),
    }

    guard = models.ForeignKey(Guard, on_delete=models.PROTECT, related_name='rewards')
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rewards',
    )
    reason = models.CharField(max_length=150, choices=Reason.choices)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        editable=False,
    )
    date_awarded = models.DateField()

    class Meta:
        ordering = ['-date_awarded']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name='reward_amount_nonnegative'),
        ]

    @property
    def percentage(self):
        return self.PERCENTAGES.get(self.reason)

    def __str__(self):
        return f'{self.guard} — {self.reason} ({self.amount})'


class AuditLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=150)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} — {self.created_at}'
