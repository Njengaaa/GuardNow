from django.contrib import admin
from django.contrib.auth import password_validation
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django import forms

from .models import AuditLog, Assignment, Guard, GuardRequest, Invoice, Payment, Rank, Reward, Shift, ShiftLog, Site, User


class GuardLinkAdminCreationForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm password', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('email', 'full_name', 'phone', 'role')

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'The passwords do not match.')
        if password1:
            try:
                password_validation.validate_password(password1, self.instance)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.is_staff = user.role == User.Role.ADMIN
        if commit:
            user.save()
        return user


@admin.register(User)
class GuardLinkUserAdmin(UserAdmin):
    add_form = GuardLinkAdminCreationForm
    ordering = ['email']
    list_display = ['email', 'full_name', 'role', 'is_staff', 'is_active']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal information', {'fields': ('full_name', 'phone', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'full_name', 'phone', 'role', 'password1', 'password2')}),
    )
    search_fields = ['email', 'full_name']

    def save_model(self, request, obj, form, change):
        if not obj.is_superuser:
            obj.is_staff = obj.role == User.Role.ADMIN
        super().save_model(request, obj, form, change)


@admin.register(Guard)
class GuardAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'rank', 'status', 'phone', 'date_hired']
    list_filter = ['rank', 'status']
    search_fields = ['full_name', 'national_id']


@admin.register(GuardRequest)
class GuardRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'client', 'site', 'rank', 'shift', 'guards_needed', 'start_date', 'status']
    list_filter = ['status', 'rank']
    search_fields = ['client__email', 'site__site_name']


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ['guard', 'request', 'shift', 'start_date', 'end_date']
    list_filter = ['shift']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['guard', 'period_start', 'period_end', 'total_amount', 'status']
    list_filter = ['status']


admin.site.register([Rank, Site, Shift, ShiftLog, Reward])
admin.site.register(Invoice)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'action', 'ip_address']
    list_filter = ['action', 'created_at']
    search_fields = ['user__email', 'action', 'details']
    readonly_fields = ['user', 'action', 'details', 'ip_address', 'created_at']
