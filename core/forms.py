from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import (
    Assignment,
    Guard,
    GuardRequest,
    Payment,
    Rank,
    Reward,
    Shift,
    ShiftLog,
    Site,
    User,
)


class ClientRegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=100)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password')
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'The passwords do not match.')
        if password1:
            candidate = User(
                email=cleaned_data.get('email', ''),
                full_name=cleaned_data.get('full_name', ''),
            )
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned_data

    def save(self):
        return User.objects.create_user(
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1'],
            full_name=self.cleaned_data['full_name'],
            phone=self.cleaned_data['phone'],
            role=User.Role.CLIENT,
        )


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label='Email address')


class GuardRequestForm(forms.Form):
    rank = forms.ModelChoiceField(queryset=Rank.objects.none())
    shift = forms.ModelChoiceField(queryset=Shift.objects.none())
    guards_needed = forms.IntegerField(min_value=1, initial=1)
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    site_name = forms.CharField(max_length=100)
    address = forms.CharField(max_length=150, label='Site address')
    county = forms.CharField(max_length=50)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rank'].queryset = Rank.objects.all()
        self.fields['shift'].queryset = Shift.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'End date must be on or after the start date.')
        return cleaned_data

    def save(self, client):
        site, _ = Site.objects.get_or_create(
            client=client,
            site_name=self.cleaned_data['site_name'],
            defaults={
                'address': self.cleaned_data['address'],
                'county': self.cleaned_data['county'],
            },
        )
        site.address = self.cleaned_data['address']
        site.county = self.cleaned_data['county']
        site.save(update_fields=['address', 'county'])
        return GuardRequest.objects.create(
            client=client,
            site=site,
            rank=self.cleaned_data['rank'],
            shift=self.cleaned_data['shift'],
            guards_needed=self.cleaned_data['guards_needed'],
            start_date=self.cleaned_data['start_date'],
            end_date=self.cleaned_data['end_date'],
        )


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ['guard', 'shift', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, service_request, *args, **kwargs):
        self.service_request = service_request
        super().__init__(*args, **kwargs)
        self.instance.request = service_request
        self.fields['guard'].queryset = Guard.objects.filter(
            rank=service_request.rank,
            status=Guard.Status.AVAILABLE,
        )
        self.fields['start_date'].initial = service_request.start_date
        self.fields['end_date'].initial = service_request.end_date
        if service_request.shift_id:
            self.fields['shift'].queryset = Shift.objects.filter(pk=service_request.shift_id)
            self.fields['shift'].initial = service_request.shift_id
        else:
            self.fields['shift'].queryset = Shift.objects.all()

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.request = self.service_request
        if commit:
            assignment.full_clean()
            assignment.save()
            assignment.guard.status = Guard.Status.DEPLOYED
            assignment.guard.save(update_fields=['status'])
        return assignment


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = ShiftLog
        fields = ['work_date', 'attendance']
        widgets = {'work_date': forms.DateInput(attrs={'type': 'date'})}


class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ['guard', 'reason', 'date_awarded']
        widgets = {'date_awarded': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['guard'].queryset = Guard.objects.all()
        self.fields['reason'].help_text = (
            'The reward amount is calculated from the guard’s base pay for the payment period.'
        )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('reason') == Reward.Reason.PERFECT_ATTENDANCE:
            guard = cleaned_data.get('guard')
            date_awarded = cleaned_data.get('date_awarded')
            if guard and date_awarded:
                payment = Payment.objects.filter(
                    guard=guard,
                    period_start__lte=date_awarded,
                    period_end__gte=date_awarded,
                ).order_by('-period_end').first()
                if payment is None:
                    self.add_error(
                        'date_awarded',
                        'Calculate a payment for this period before awarding Perfect Attendance.',
                    )
                elif not payment.has_perfect_attendance():
                    self.add_error(
                        'date_awarded',
                        'Perfect Attendance requires every scheduled shift-day in the payment period to be Present.',
                    )
        return cleaned_data


class PaymentPeriodForm(forms.Form):
    guard = forms.ModelChoiceField(queryset=Guard.objects.none())
    period_start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    period_end = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['guard'].queryset = Guard.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        guard = cleaned_data.get('guard')
        start = cleaned_data.get('period_start')
        end = cleaned_data.get('period_end')
        if start and end and end < start:
            self.add_error('period_end', 'Period end must be on or after its start.')
        elif guard and start and end:
            overlap = Payment.objects.filter(
                guard=guard,
                period_start__lte=end,
                period_end__gte=start,
            ).exclude(period_start=start, period_end=end)
            if overlap.exists():
                self.add_error('period_start', 'This period overlaps another payment period for the same guard.')
        return cleaned_data


class PaymentStatusForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['status']
