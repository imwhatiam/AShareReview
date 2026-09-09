from datetime import datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import DataVersion
from core.services.file_cache import FileCache
from eastmoney.models import EastmoneySectorFundFlowRun, EastmoneySectorFundFlowSnapshot


class EastmoneyApiTests(TestCase):
    databases = {'default', 'eastmoney'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        self.user = get_user_model().objects.create_user(
            username='eastmoney-user', password='correct-password'
        )
        snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 15, 0))
        for code, name, net_inflow in (
            ('A', '甲行业', '100000000'),
            ('B', '乙行业', '-200000000'),
        ):
            EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
                sector_code=code,
                sector_name=name,
                trade_date=self.trade_date,
                snapshot_time=snapshot_time,
                main_net_inflow=Decimal(net_inflow),
                source_batch_id='published-snapshot',
            )
        DataVersion.objects.create(
            dataset_key='eastmoney_sector_fund_flow',
            version='eastmoney-test-version',
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
        response = self.client.get('/api/eastmoney/sectors/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('eastmoney.services.read_path.default_file_cache')
    def test_intraday_reads_database_then_file_cache_with_shared_envelope(self, cache_factory):
        cache_factory.return_value = self.cache

        first = self._authenticated_client().get(
            '/api/eastmoney/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )
        second = self._authenticated_client().get(
            '/api/eastmoney/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['status'], 'ok')
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        self.assertEqual(first.json()['data_version'], 'eastmoney-test-version')
        self.assertEqual(first.json()['source'], 'database')
        self.assertEqual(
            [item['code'] for item in first.json()['data']['series']], ['A', 'B']
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['source'], 'cache')
        self.assertEqual(second.json()['data'], first.json()['data'])

    def test_explicit_invalid_parameters_are_rejected_without_falling_back(self):
        client = self._authenticated_client()

        malformed = client.get('/api/eastmoney/sectors/intraday/?date=2026-9-8')
        invalid_days = client.get('/api/eastmoney/sectors/intraday/history/?days=2')
        unavailable = client.get('/api/eastmoney/sectors/?date=2026-09-07')

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_DATE')
        self.assertEqual(invalid_days.status_code, 400)
        self.assertEqual(invalid_days.json()['error']['code'], 'INVALID_PARAMETER')
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(unavailable.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    def test_partial_snapshot_exposes_missing_direction_as_a_warning(self):
        DataVersion.objects.all().delete()
        snapshot_time = timezone.make_aware(datetime(2026, 9, 8, 15, 0))
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').all().delete()
        EastmoneySectorFundFlowRun.objects.using('eastmoney').create(
            source_batch_id='partial-inflow-batch',
            trade_date=self.trade_date,
            snapshot_time=snapshot_time,
            status=EastmoneySectorFundFlowRun.Status.PARTIAL,
            inflow_status=EastmoneySectorFundFlowRun.DirectionStatus.COMPLETE,
            outflow_status=EastmoneySectorFundFlowRun.DirectionStatus.FAILED,
        )
        EastmoneySectorFundFlowSnapshot.objects.using('eastmoney').create(
            sector_code='A',
            sector_name='甲行业',
            trade_date=self.trade_date,
            snapshot_time=snapshot_time,
            main_net_inflow=Decimal('100000000'),
            source_batch_id='partial-inflow-batch',
        )
        DataVersion.objects.create(
            dataset_key='eastmoney_sector_fund_flow',
            version='eastmoney-partial-version',
            business_date=self.trade_date,
            status=DataVersion.Status.PARTIAL,
            expected_record_count=2,
            actual_record_count=1,
            missing_record_count=1,
        )

        response = self._authenticated_client().get(
            '/api/eastmoney/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'partial')
        self.assertEqual(response.json()['warnings'], ['东方财富资金流缺少流出榜数据。'])
        self.assertEqual(response.json()['data']['missing_directions'], ['outflow'])

    @patch('eastmoney.services.fetcher.EastmoneySectorFundFlowFetcher.fetch')
    def test_no_data_returns_unavailable_without_starting_remote_collection(self, fetch):
        DataVersion.objects.all().delete()

        response = self._authenticated_client().get('/api/eastmoney/sectors/intraday/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'preparing')
        self.assertEqual(response.json()['preparation']['state'], 'unavailable')
        self.assertEqual(response.json()['error']['code'], 'DATA_PREPARING')
        fetch.assert_not_called()

    @patch('eastmoney.services.read_path.default_file_cache')
    def test_dates_lists_complete_and_partial_published_business_dates(self, cache_factory):
        cache_factory.return_value = self.cache
        DataVersion.objects.create(
            dataset_key='eastmoney_sector_fund_flow',
            version='eastmoney-partial-date-version',
            business_date=datetime(2026, 9, 7).date(),
            status=DataVersion.Status.PARTIAL,
            expected_record_count=2,
            actual_record_count=1,
            missing_record_count=1,
        )

        response = self._authenticated_client().get('/api/eastmoney/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
        self.assertEqual(response.json()['source'], 'database')
