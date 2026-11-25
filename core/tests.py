from datetime import date, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    Assignment,
    Guard,
    GuardRequest,
    Invoice,
    Payment,
    Rank,
    Reward,
    Shift,
    ShiftLog,
    Site,
    User,
)


class GuardLinkTestData(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            email='client@example.com',
            password='StrongPass!47',
            full_name='Client One',
        )
        self.admin_user = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminStrong!47',
            full_name='Admin One',
        )
        self.rank = Rank.objects.create(
            name='Guard',
            guard_daily_rate=Decimal('1200.00'),
            client_daily_rate=Decimal('1800.00'),
        )
        self.day_shift = Shift.objects.create(name='Day', start_time=time(8), end_time=time(16))
        self.guard = Guard.objects.create(
            full_name='Guard One',
            national_id='ID-100',
            phone='0700000000',
            rank=self.rank,
            date_hired=date(2025, 1, 1),
        )
        self.site = Site.objects.create(
            client=self.client_user,
            site_name='Main Site',
            address='1 Main Road',
            county='Nairobi',
        )

    def make_request(self, client=None, start=date(2026, 11, 10), end=date(2026, 11, 12)):
        return GuardRequest.objects.create(
            client=client or self.client_user,
            site=self.site,
            rank=self.rank,
            shift=self.day_shift,
            guards_needed=1,
            start_date=start,
            end_date=end,
        )


class AuthenticationAndClientFlowTests(GuardLinkTestData):
    def test_login_requires_two_factor_verification(self):
        response = self.client.post(reverse('login'), {
            'username': 'client@example.com',
            'password': 'StrongPass!47',
        })
        self.assertRedirects(response, reverse('verify_two_factor'))
        code = self.client.session['pending_2fa_code']
        response = self.client.post(reverse('verify_two_factor'), {'code': code})
        self.assertRedirects(response, reverse('client_dashboard'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_password_reset_pages_are_available(self):
        self.assertEqual(
            self.client.get(reverse('password_reset')).status_code,
            200,
        )

    def test_registration_creates_hashed_password_and_signs_client_in(self):
        response = self.client.post(reverse('register'), {
            'full_name': 'New Client',
            'email': 'new@example.com',
            'phone': '0712345678',
            'password1': 'Some!StrongPassword493',
            'password2': 'Some!StrongPassword493',
        })

        user = User.objects.get(email='new@example.com')
        self.assertRedirects(response, reverse('client_dashboard'))
        self.assertTrue(user.check_password('Some!StrongPassword493'))
        self.assertNotEqual(user.password, 'Some!StrongPassword493')
        self.assertEqual(user.role, User.Role.CLIENT)

    def test_login_uses_email_and_bad_password_is_rejected(self):
        response = self.client.post(reverse('login'), {
            'username': 'client@example.com',
            'password': 'StrongPass!47',
        })
        self.assertRedirects(response, reverse('verify_two_factor'))
        code = self.client.session['pending_2fa_code']
        response = self.client.post(reverse('verify_two_factor'), {'code': code})
        self.assertRedirects(response, reverse('client_dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.client_user.pk)

        self.client.logout()
        response = self.client.post(reverse('login'), {
            'username': 'client@example.com',
            'password': 'incorrect',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())

    def test_client_can_submit_and_view_request(self):
        self.client.force_login(self.client_user)
        response = self.client.post(reverse('create_request'), {
            'rank': self.rank.pk,
            'shift': self.day_shift.pk,
            'guards_needed': 2,
            'start_date': '2026-11-10',
            'end_date': '2026-11-12',
            'site_name': 'Warehouse',
            'address': '2 Industrial Road',
            'county': 'Nairobi',
        })

        self.assertRedirects(response, reverse('client_dashboard'))
        created_request = GuardRequest.objects.get(site__site_name='Warehouse')
        self.assertEqual(created_request.client, self.client_user)
        self.assertEqual(created_request.shift, self.day_shift)
        self.assertEqual(created_request.status, GuardRequest.Status.PENDING)
        self.assertContains(self.client.get(reverse('client_dashboard')), 'Warehouse')

    def test_request_requires_a_client_selected_shift(self):
        from .forms import GuardRequestForm

        form = GuardRequestForm({
            'rank': self.rank.pk,
            'guards_needed': 1,
            'start_date': '2026-11-10',
            'end_date': '2026-11-12',
            'site_name': 'Warehouse',
            'address': '2 Industrial Road',
            'county': 'Nairobi',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('shift', form.errors)

    def test_client_cannot_access_admin_panel_or_other_clients_requests(self):
        other_client = User.objects.create_user(
            email='other@example.com',
            password='StrongPass!47',
            full_name='Other Client',
        )
        other_request = self.make_request(client=other_client)
        self.client.force_login(self.client_user)

        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('client_dashboard'))
        self.assertNotContains(self.client.get(reverse('client_dashboard')), f'Request #{other_request.pk}')


class DeploymentAndPayrollTests(GuardLinkTestData):
    def setUp(self):
        super().setUp()
        self.service_request = self.make_request()

    def test_assignment_form_lists_only_available_guards(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.guards_needed = 2
        self.service_request.save(update_fields=['status', 'guards_needed'])
        Assignment.objects.create(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        self.guard.status = Guard.Status.DEPLOYED
        self.guard.save(update_fields=['status'])
        available_guard = Guard.objects.create(
            full_name='Available Guard',
            national_id='ID-101',
            phone='0700000001',
            rank=self.rank,
            status=Guard.Status.AVAILABLE,
            date_hired=date(2025, 1, 1),
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('assign_guard', args=[self.service_request.pk]))
        guard_choices = response.context['form'].fields['guard'].queryset

        self.assertIn(available_guard, guard_choices)
        self.assertNotIn(self.guard, guard_choices)

    def test_admin_can_approve_and_assign_a_guard(self):
        self.client.force_login(self.admin_user)
        status_response = self.client.post(
            reverse('update_request_status', args=[self.service_request.pk]),
            {'status': GuardRequest.Status.APPROVED},
        )
        assign_response = self.client.post(
            reverse('assign_guard', args=[self.service_request.pk]),
            {
                'guard': self.guard.pk,
                'shift': self.day_shift.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-11-12',
            },
        )

        self.assertRedirects(status_response, reverse('admin_dashboard'))
        self.assertRedirects(assign_response, reverse('admin_dashboard'))
        self.assertEqual(Assignment.objects.count(), 1)
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.status, Guard.Status.DEPLOYED)
        admin_dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertContains(admin_dashboard, 'Day')
        self.assertContains(admin_dashboard, 'Client invoices')

    def test_overlapping_assignment_is_rejected_but_separate_shift_is_allowed(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.save(update_fields=['status'])
        first = Assignment(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        first.full_clean()
        first.save()
        overlapping = Assignment(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 11),
            end_date=date(2026, 11, 11),
        )
        with self.assertRaisesMessage(ValidationError, 'already has an assignment'):
            overlapping.full_clean()

        night_shift = Shift.objects.create(name='Night', start_time=time(20), end_time=time(4))
        second_request = self.make_request(start=date(2026, 11, 10), end=date(2026, 11, 12))
        second_request.status = GuardRequest.Status.APPROVED
        second_request.shift = night_shift
        second_request.save(update_fields=['status', 'shift'])
        separate_shift = Assignment(
            request=second_request,
            guard=self.guard,
            shift=night_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        separate_shift.full_clean()

    def test_payment_uses_present_attendance_and_rewards(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.save(update_fields=['status'])
        assignment = Assignment.objects.create(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        ShiftLog.objects.create(
            assignment=assignment,
            work_date=date(2026, 11, 10),
            attendance=ShiftLog.Attendance.PRESENT,
        )
        ShiftLog.objects.create(
            assignment=assignment,
            work_date=date(2026, 11, 11),
            attendance=ShiftLog.Attendance.ABSENT,
        )
        ShiftLog.objects.create(
            assignment=assignment,
            work_date=date(2026, 11, 12),
            attendance=ShiftLog.Attendance.LATE,
        )
        reward = Reward.objects.create(
            guard=self.guard,
            reason=Reward.Reason.EXCELLENT_SERVICE,
            date_awarded=date(2026, 11, 11),
        )
        lower_reward = Reward.objects.create(
            guard=self.guard,
            reason=Reward.Reason.CLIENT_PERFECT_RATING,
            date_awarded=date(2026, 11, 12),
        )
        payment = Payment.objects.create(
            guard=self.guard,
            period_start=date(2026, 11, 10),
            period_end=date(2026, 11, 12),
        )

        payment.recalculate()
        payment.refresh_from_db()
        reward.refresh_from_db()
        lower_reward.refresh_from_db()

        self.assertEqual(payment.shifts_worked, 1)
        self.assertEqual(payment.base_amount, Decimal('1200.00'))
        self.assertEqual(payment.bonus_amount, Decimal('300.00'))
        self.assertEqual(payment.total_amount, Decimal('1500.00'))
        self.assertEqual(reward.payment, payment)
        self.assertEqual(reward.amount, Decimal('300.00'))
        self.assertEqual(lower_reward.payment, payment)
        self.assertEqual(lower_reward.amount, Decimal('0.00'))

    def test_perfect_attendance_reward_is_percentage_and_requires_every_shift_present(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.save(update_fields=['status'])
        assignment = Assignment.objects.create(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        attendance = []
        for work_date, status in (
            (date(2026, 11, 10), ShiftLog.Attendance.PRESENT),
            (date(2026, 11, 11), ShiftLog.Attendance.PRESENT),
            (date(2026, 11, 12), ShiftLog.Attendance.ABSENT),
        ):
            attendance.append(ShiftLog.objects.create(
                assignment=assignment,
                work_date=work_date,
                attendance=status,
            ))
        payment = Payment.objects.create(
            guard=self.guard,
            period_start=date(2026, 11, 10),
            period_end=date(2026, 11, 12),
        )
        payment.recalculate()
        self.client.force_login(self.admin_user)
        reward_response = self.client.post(reverse('create_reward'), {
            'guard': self.guard.pk,
            'reason': Reward.Reason.PERFECT_ATTENDANCE,
            'date_awarded': '2026-11-12',
        })
        self.assertEqual(reward_response.status_code, 200)
        self.assertContains(reward_response, 'requires every scheduled shift-day')
        self.assertFalse(Reward.objects.exists())

        attendance[-1].attendance = ShiftLog.Attendance.PRESENT
        attendance[-1].save(update_fields=['attendance'])
        reward_response = self.client.post(reverse('create_reward'), {
            'guard': self.guard.pk,
            'reason': Reward.Reason.PERFECT_ATTENDANCE,
            'date_awarded': '2026-11-12',
        })
        self.assertRedirects(reward_response, reverse('payments'))
        reward = Reward.objects.get(guard=self.guard)
        payment.refresh_from_db()
        reward.refresh_from_db()
        self.assertEqual(payment.base_amount, Decimal('3600.00'))
        self.assertEqual(payment.bonus_amount, Decimal('360.00'))
        self.assertEqual(reward.amount, Decimal('360.00'))

        attendance[-1].attendance = ShiftLog.Attendance.LATE
        attendance[-1].save(update_fields=['attendance'])
        payment.recalculate()
        payment.refresh_from_db()
        reward.refresh_from_db()
        self.assertEqual(payment.bonus_amount, Decimal('0.00'))
        self.assertEqual(reward.amount, Decimal('0.00'))

    def test_reward_form_offers_reasons_and_hides_manual_amount(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('create_reward'))

        self.assertContains(response, 'Excellent Service (25%)')
        self.assertContains(response, 'Good Service (5%)')
        self.assertContains(response, 'Perfect Attendance (10%)')
        self.assertContains(response, 'Client Perfect Rating (5%)')
        self.assertNotContains(response, 'name="amount"')

    def test_overlapping_payment_period_is_rejected(self):
        Payment.objects.create(
            guard=self.guard,
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 15),
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('payments'), {
            'guard': self.guard.pk,
            'period_start': '2026-11-10',
            'period_end': '2026-11-20',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'overlaps another payment period')
        self.assertEqual(Payment.objects.count(), 1)

    def test_invoice_uses_scheduled_guard_days_and_client_can_view_when_issued(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.shift = self.day_shift
        self.service_request.save(update_fields=['status', 'shift'])
        assignment = Assignment.objects.create(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        ShiftLog.objects.create(
            assignment=assignment,
            work_date=date(2026, 11, 10),
            attendance=ShiftLog.Attendance.ABSENT,
        )
        self.client.force_login(self.admin_user)
        admin_page = self.client.get(reverse('invoices'))
        self.assertEqual(admin_page.status_code, 200)
        self.assertContains(admin_page, 'Requests ready for invoicing')
        response = self.client.post(
            reverse('create_invoice', args=[self.service_request.pk]),
        )

        invoice = Invoice.objects.get(request=self.service_request)
        self.assertRedirects(response, reverse('invoices'))
        self.assertEqual(invoice.guard_days, 3)
        self.assertEqual(invoice.client_daily_rate, Decimal('1800.00'))
        self.assertEqual(invoice.total_amount, Decimal('5400.00'))
        self.assertEqual(invoice.status, Invoice.Status.DRAFT)

        self.client.force_login(self.client_user)
        self.assertNotContains(
            self.client.get(reverse('client_dashboard')),
            '5400.00',
        )
        self.client.force_login(self.admin_user)
        self.client.post(
            reverse('update_invoice_status', args=[invoice.pk]),
            {'status': Invoice.Status.ISSUED},
        )
        self.client.force_login(self.client_user)
        client_response = self.client.get(reverse('client_dashboard'))
        self.assertContains(client_response, '5400.00')
        self.assertContains(client_response, 'Issued')

        self.client.force_login(self.admin_user)
        paid_response = self.client.post(
            reverse('update_invoice_status', args=[invoice.pk]),
            {'status': Invoice.Status.PAID},
        )
        invoice.refresh_from_db()
        self.assertRedirects(paid_response, reverse('invoices'))
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_invoice_cannot_be_created_until_every_requested_guard_is_assigned(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.guards_needed = 2
        self.service_request.save(update_fields=['status', 'guards_needed'])
        Assignment.objects.create(
            request=self.service_request,
            guard=self.guard,
            shift=self.day_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse('create_invoice', args=[self.service_request.pk]),
        )

        self.assertRedirects(response, reverse('invoices'))
        self.assertFalse(Invoice.objects.filter(request=self.service_request).exists())

    def test_assignment_shift_must_match_requested_shift(self):
        self.service_request.status = GuardRequest.Status.APPROVED
        self.service_request.shift = self.day_shift
        self.service_request.save(update_fields=['status', 'shift'])
        night_shift = Shift.objects.create(name='Night', start_time=time(20), end_time=time(4))
        assignment = Assignment(
            request=self.service_request,
            guard=self.guard,
            shift=night_shift,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
        )

        with self.assertRaisesMessage(ValidationError, 'must match the shift requested'):
            assignment.full_clean()

    def test_admin_pages_require_admin_login(self):
        self.client.force_login(self.client_user)
        response = self.client.get(reverse('payments'))
        self.assertRedirects(response, reverse('client_dashboard'))

    def test_admin_can_sign_in_and_open_user_management(self):
        response = self.client.post(reverse('login'), {
            'username': 'admin@example.com',
            'password': 'AdminStrong!47',
        })
        self.assertRedirects(response, reverse('verify_two_factor'))
        code = self.client.session['pending_2fa_code']
        response = self.client.post(reverse('verify_two_factor'), {'code': code})
        self.assertRedirects(response, reverse('admin_dashboard'))
        response = self.client.post('/admin/core/user/add/', {
            'email': 'new-admin@example.com',
            'full_name': 'New Administrator',
            'phone': '0700000001',
            'role': User.Role.ADMIN,
            'password1': 'OtherStrong!83Password',
            'password2': 'OtherStrong!83Password',
            '_save': 'Save',
        })
        new_admin = User.objects.get(email='new-admin@example.com')
        self.assertRedirects(
            response,
            reverse('admin:core_user_change', args=[new_admin.pk]),
        )
        self.assertTrue(new_admin.is_staff)
        response = self.client.get('/admin/core/user/add/')
        self.assertEqual(response.status_code, 200)
