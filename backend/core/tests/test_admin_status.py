from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import DataVersion, ModuleRunStatus


class AdminStatusTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username='admin-user',
            password='password',
            is_staff=True,
        )
        self.user = user_model.objects.create_user(
            username='regular-user',
            password='password',
        )

    def test_staff_can_view_module_status_with_safe_operational_fields(self):
        ModuleRunStatus.objects.create(
            module_id='kaipanla',
            dataset_key='sector_fund_flow',
            status=ModuleRunStatus.Status.SUCCESS,
            completeness=DataVersion.Status.COMPLETE,
            business_date=date(2026, 9, 8),
            source_data_version='kaipanla-20260908-v1',
            serving_stale=False,
            consecutive_failure_count=0,
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('admin:core_modulerunstatus_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'kaipanla')
        self.assertContains(response, 'sector_fund_flow')
        self.assertContains(response, 'kaipanla-20260908-v1')
        self.assertContains(response, '业务日期')
        self.assertContains(response, '连续失败次数')

    def test_non_staff_user_cannot_access_the_status_center(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin:core_modulerunstatus_changelist'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_historical_module_identifier_renders_without_importing_a_business_app(self):
        ModuleRunStatus.objects.create(
            module_id='retired_module',
            dataset_key='historical_dataset',
            status=ModuleRunStatus.Status.FAILED,
            completeness=DataVersion.Status.FAILED,
            serving_stale=True,
            consecutive_failure_count=1,
        )
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('admin:core_modulerunstatus_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'retired_module')

    def test_admin_redacts_sensitive_values_in_error_summaries(self):
        from core.services.status_summary import safe_error_summary

        summary = safe_error_summary(
            'request failed: api_key=super-secret '
            'token: another-secret Authorization: Bearer third-secret'
        )

        self.assertNotIn('super-secret', summary)
        self.assertNotIn('another-secret', summary)
        self.assertNotIn('third-secret', summary)
        self.assertIn('[REDACTED]', summary)

    def test_status_center_is_read_only(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('admin:core_modulerunstatus_add'))

        self.assertEqual(response.status_code, 403)
