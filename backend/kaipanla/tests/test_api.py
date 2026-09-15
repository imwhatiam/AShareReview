from datetime import datetime, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

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
            )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def _authenticated_client(self):
        self.client.force_login(self.user)
        return self.client

    def patch_now(self, *parts):
        """固定默认入口看到的那一刻。

        默认入口按本模块自己的最新快照日解析，并且只在"今天该有却还没有"时才
        需要区分"还在盘中"与"已经收盘"，所以"现在几点"会改变它走哪条分支。
        """
        return patch(
            'django.utils.timezone.now',
            return_value=timezone.make_aware(datetime(*parts)),
        )

    def test_endpoints_require_an_authenticated_session(self):
        response = self.client.get('/api/kaipanla/sectors/')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'AUTH_REQUIRED')

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_intraday_reads_database_then_file_cache_with_shared_envelope(self, cache_factory):
        cache_factory.return_value = self.cache
        written_at = timezone.now() - timedelta(days=30)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').update(created_at=written_at)

        first = self._authenticated_client().get(
            '/api/kaipanla/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )
        second = self._authenticated_client().get(
            '/api/kaipanla/sectors/intraday/?date=2026-09-08&inflow_top=1&outflow_top=1'
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['status'], 'ok')
        self.assertEqual(first.json()['business_date'], '2026-09-08')
        # 信封里没有版本号：缓存身份是"哪一天的哪个采集槽"，它留在服务端的
        # `ReadResult.cache_identity`，属于缓存决策，不是响应字段。
        self.assertNotIn('data_version', first.json())
        self.assertEqual(first.json()['source'], 'database')
        self.assertFalse(first.json()['stale'])
        # 「更新于」显示的时刻 = 这批快照写进库的时刻，取数据库与取文件缓存给的是同一个值
        # （文件缓存只存载荷，信封每次重建）。它绝不等于 generated_at。
        self.assertEqual(
            datetime.fromisoformat(first.json()['data_updated_at']), written_at
        )
        self.assertEqual(second.json()['data_updated_at'], first.json()['data_updated_at'])
        self.assertNotEqual(
            first.json()['data_updated_at'], first.json()['generated_at']
        )
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

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_dates_lists_the_stored_business_dates(self, cache):
        """不挂文件缓存：`/dates/` 的缓存身份只看最新快照日与槽位，不看日期集合。

        同一进程里前面的用例把 `['2026-09-08']` 写进真实缓存目录后，本用例再加一天
        仍然会命中那条陈旧记录（`source` 变成 `cache`）。兄弟模块的 test_api 都对
        `default_file_cache` 做了隔离，这里此前漏了。
        """
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='A',
            sector_name='甲行业',
            trade_date=datetime(2026, 9, 7).date(),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 7, 15, 0)),
            main_net_inflow=Decimal('100000000'),
        )

        response = self._authenticated_client().get('/api/kaipanla/dates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['dates'], ['2026-09-08', '2026-09-07'])
        self.assertEqual(response.json()['source'], 'database')

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_dates_without_any_snapshot_is_404(self, cache):
        """纯元信息端点被前端轮询：没有数据就是 404，它没有任何回源能力。"""
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').all().delete()

        response = self._authenticated_client().get('/api/kaipanla/dates/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'DATA_NOT_AVAILABLE')

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_the_default_entry_serves_today_once_today_has_a_snapshot(self, cache):
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='C',
            sector_name='丙行业',
            trade_date=datetime(2026, 9, 9).date(),
            snapshot_time=timezone.make_aware(datetime(2026, 9, 9, 9, 35)),
            main_net_inflow=Decimal('300000000'),
        )

        with self.patch_now(2026, 9, 9, 9, 40):
            response = self._authenticated_client().get('/api/kaipanla/sectors/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['business_date'], '2026-09-09')
        self.assertFalse(response.json()['stale'])

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_the_default_entry_answers_202_while_today_is_still_collecting(self, cache):
        with self.patch_now(2026, 9, 9, 9, 32):
            response = self._authenticated_client().get('/api/kaipanla/sectors/')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'preparing')
        self.assertEqual(response.json()['error']['code'], 'DATA_PREPARING')

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_the_default_entry_serves_the_last_stored_day_as_stale_after_the_close(self, cache):
        with self.patch_now(2026, 9, 9, 20, 0):
            response = self._authenticated_client().get('/api/kaipanla/sectors/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['business_date'], '2026-09-08')
        self.assertTrue(response.json()['stale'])
        self.assertTrue(response.json()['warnings'])
