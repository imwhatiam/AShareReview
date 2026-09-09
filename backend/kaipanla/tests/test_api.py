from datetime import datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion
from core.services.file_cache import FileCache
from kaipanla.models import KaipanlaSectorFundFlowSnapshot


class KaipanlaApiTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        self.user = get_user_model().objects.create_user(
            username='kaipanla-user', password='correct-password'
        )
        for code, name, net_inflow in (
            ('A', '甲行业', '100000000'),
            ('B', '乙行业', '-200000000'),
        ):
            KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
                sector_code=code,
                sector_name=name,
                trade_date=self.trade_date,
                snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
                main_net_inflow=Decimal(net_inflow),
                source_batch_id='published-snapshot',
            )
        DataVersion.objects.create(
            dataset_key='kaipanla_sector_fund_flow',
            version='kaipanla-test-version',
            business_date=self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=2,
            actual_record_count=2,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _authenticated_client(self):
        self.client.force_login(self.user)
        return self.client

    def test_endpoints_require_an_authenticated_session(self):
        response = self.client.get('/api/kaipanla/sectors/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_intraday_reads_database_then_file_cache_with_shared_envelope(self, cache_factory):
        cache_factory.return_value = self.cache

        first = self._authenticated_client().get(
            '/api/kaipanla/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )
        second = self._authenticated_client().get(
            '/api/kaipanla/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['status'], 'ok')
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        self.assertEqual(first.json()['data_version'], 'kaipanla-test-version')
        self.assertEqual(first.json()['source'], 'database')
        self.assertEqual(
            [item['code'] for item in first.json()['data']['series']], ['A', 'B']
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    def test_explicit_invalid_parameters_are_rejected_without_falling_back(self):
        client = self._authenticated_client()

        malformed = client.get('/api/kaipanla/sectors/intraday/?date=2026-9-8')
        invalid_days = client.get('/api/kaipanla/sectors/intraday/history/?days=2')
        unavailable = client.get('/api/kaipanla/sectors/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(invalid_days.status_code, 400)
        self.assertEqual(invalid_days.json()['error']['code'], 'INVALID_PARAMETER')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    def test_dates_lists_only_published_complete_business_dates(self):
        DataVersion.objects.create(
            dataset_key='kaipanla_sector_fund_flow',
            version='kaipanla-partial-version',
            business_date=datetime(2026, 9, 7).date(),
            status=DataVersion.Status.PARTIAL,
            expected_record_count=2,
            actual_record_count=1,
        )

        response = self._authenticated_client().get('/api/kaipanla/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08'])
        self.assertEqual(response.json()['source'], 'database')

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch('kaipanla.services.read_path._repair_current_snapshot')
    def test_missing_data_reports_sync_in_progress_when_repair_lock_is_held(
        self, repair, can_repair
    ):
        from core.api.errors import ApiError, ErrorCode

        DataVersion.objects.all().delete()
        repair.side_effect = ApiError(
            ErrorCode.SYNC_IN_PROGRESS,
            '开盘啦板块资金流正在同步，请稍后重试。',
            http_status=409,
            preparation_state='syncing',
        )

        response = self._authenticated_client().get('/api/kaipanla/sectors/intraday/')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'SYNC_IN_PROGRESS')
        can_repair.assert_called_once()
        repair.assert_called_once()
