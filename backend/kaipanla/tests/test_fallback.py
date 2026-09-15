from datetime import datetime, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.api.errors import ApiError, ErrorCode
from core.services.cache_keys import build_cache_key
from core.services.file_cache import FileCache
from kaipanla.models import KaipanlaSectorFundFlowSnapshot


def frozen_at(*parts):
    """Fix "now" at the given Shanghai moment.

    The default entry asks the clock two things — which trading day should
    already have a snapshot, and whether today's collection can still be on its
    way — so the tests that exercise it have to stop time. Everything else here
    depends on the database alone.
    """
    return patch(
        'django.utils.timezone.now',
        return_value=timezone.make_aware(datetime(*parts)),
    )


def store(trade_date, hour=15, minute=0, code='A', name='甲行业', net_inflow='100000000'):
    """Append one sector row to a slot, exactly as a collection would."""
    return KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
        sector_code=code,
        sector_name=name,
        trade_date=trade_date,
        snapshot_time=timezone.make_aware(
            datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute)
        ),
        main_net_inflow=Decimal(net_inflow),
    )


class KaipanlaExpectedSnapshotDateTests(SimpleTestCase):
    """默认入口只回答"该有快照的最新交易日"，不碰公共日行情日期。"""

    def test_before_the_open_a_trading_day_is_not_expected_yet(self):
        from kaipanla.services.read_path import _latest_expected_snapshot_date

        with frozen_at(2026, 9, 9, 8, 30):
            self.assertEqual(
                _latest_expected_snapshot_date(), datetime(2026, 9, 8).date()
            )

    def test_a_trading_day_is_expected_from_its_first_snapshot_slot_on(self):
        from kaipanla.services.read_path import _latest_expected_snapshot_date

        for hour, minute in ((9, 30), (11, 30), (12, 20), (15, 0), (23, 59)):
            with frozen_at(2026, 9, 9, hour, minute):
                self.assertEqual(
                    _latest_expected_snapshot_date(),
                    datetime(2026, 9, 9).date(),
                    f'{hour:02d}:{minute:02d} 已开盘，当天就该有快照',
                )

    def test_a_non_trading_day_keeps_the_previous_trading_day(self):
        from kaipanla.services.read_path import _latest_expected_snapshot_date

        with frozen_at(2026, 9, 12, 10, 0):  # 周六
            self.assertEqual(
                _latest_expected_snapshot_date(), datetime(2026, 9, 11).date()
            )

    def test_today_counts_as_still_collecting_until_the_close(self):
        """盘中（含午休）"今天还没有快照"可以是"还在路上"，页面该稍后再来。"""
        from kaipanla.services.read_path import _today_is_still_collecting

        for parts in ((2026, 9, 9, 9, 31), (2026, 9, 9, 12, 0), (2026, 9, 9, 14, 59)):
            with self.subTest(parts=parts), frozen_at(*parts):
                self.assertTrue(_today_is_still_collecting())

    def test_after_the_close_or_on_a_holiday_today_is_not_collecting(self):
        """收盘后与休市日不能再承诺"准备中"：那时的缺失就是缺失。"""
        from kaipanla.services.read_path import _today_is_still_collecting

        for parts in ((2026, 9, 9, 15, 0), (2026, 9, 9, 20, 0), (2026, 9, 12, 10, 0)):
            with self.subTest(parts=parts), frozen_at(*parts):
                self.assertFalse(_today_is_still_collecting())


class KaipanlaReadPathHasNoUpstreamTests(SimpleTestCase):
    """读路径没有回源能力 —— 这是删掉 Web 侧远程修复后的核心不变量。"""

    def test_the_read_path_imports_no_upstream_client(self):
        from kaipanla.services import read_path

        for name in (
            'KaipanlaSectorFundFlowFetcher',
            'KaipanlaSectorFundFlowClient',
            'flow_client_settings',
        ):
            self.assertFalse(
                hasattr(read_path, name),
                f'读路径不该再有回源能力（{name}）；数据一律来自库与文件缓存。',
            )

    def test_the_deleted_repair_vocabulary_is_gone(self):
        from kaipanla.services import read_path

        for name in (
            'RepairOutcome',
            '_repair_current_snapshot',
            '_can_attempt_repair',
            'REPAIR_MAX_PAGES',
            'REPAIR_MAX_ROWS',
        ):
            self.assertFalse(hasattr(read_path, name), f'{name} 应随修复链路一起删除。')


class KaipanlaReadPathTests(TestCase):
    databases = {'kaipanla'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        store(self.trade_date)
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_corrupt_cache_falls_back_to_database_data(self, cache_factory):
        from kaipanla.services.read_path import read_intraday

        cache_factory.return_value = self.cache
        key = build_cache_key(
            'kaipanla',
            'sectors/intraday',
            {'date': '2026-09-08', 'inflow_top': 1, 'outflow_top': 1},
            'kaipanla:2026-09-08T15:00',
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not-json', encoding='utf-8')

        result = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(result.source, 'database')
        self.assertEqual([item['code'] for item in result.data['series']], ['A'])

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_default_entry_follows_the_newest_stored_snapshot(self, cache):
        """页面锚点是**本模块自己最新的快照日**，与公共日行情日期无关。

        回归用例（2026-09-14 现场）：盘中当天快照已经落库，而
        `stock_daily_prices` 当天还没有任何 complete 版本。旧实现锚定公共日行情
        日期，于是首屏退回前一个交易日 —— 明明手里有当天数据却不肯显示。
        """
        from kaipanla.services.read_path import read_sectors

        same_day = datetime(2026, 9, 9).date()
        store(same_day, hour=10, minute=0)

        with frozen_at(2026, 9, 9, 10, 5):
            result = read_sectors()

        self.assertEqual(result.business_date, same_day)
        self.assertFalse(result.stale)
        self.assertEqual(result.warnings, ())

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_today_without_a_snapshot_answers_202_while_today_can_still_be_collected(
        self, cache
    ):
        """今天该有还没有、而且还在盘中窗口内 → 202"正在准备中"，不拿昨天顶替。"""
        from kaipanla.services.read_path import read_sectors

        with frozen_at(2026, 9, 9, 10, 0), self.assertRaises(ApiError) as raised:
            read_sectors()

        self.assertEqual(raised.exception.code, ErrorCode.DATA_PREPARING)
        self.assertEqual(raised.exception.http_status, 202)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_a_closed_day_without_a_snapshot_serves_the_newest_one_as_stale(self, cache):
        """收盘后还是没有当天快照 → 如实返回最近可用快照并标 stale。

        以前这里会一直回 202：缺失被说成"还在准备"。收盘之后那就不是准备，是缺失。
        """
        from kaipanla.services.read_path import read_sectors

        with frozen_at(2026, 9, 9, 15, 30):
            result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertIn('最近一次可用快照', result.warnings[0])

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_a_non_trading_day_with_a_gap_serves_the_newest_one_as_stale(self, cache):
        from kaipanla.services.read_path import read_sectors

        with frozen_at(2026, 9, 12, 10, 0):  # 周六，最近交易日 09-11 没有快照
            result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_before_the_open_the_previous_close_is_served_without_a_warning(self, cache):
        """开盘前"最新交易日"仍是上一个交易日：直接服务它，不是旧数据。"""
        from kaipanla.services.read_path import read_sectors

        with frozen_at(2026, 9, 9, 8, 30):
            result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertFalse(result.stale)
        self.assertEqual(result.warnings, ())

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_no_stored_snapshot_is_404(self, cache):
        from kaipanla.services.read_path import read_sectors

        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').all().delete()

        with self.assertRaises(ApiError) as raised:
            read_sectors()

        self.assertEqual(raised.exception.code, ErrorCode.DATA_NOT_AVAILABLE)
        self.assertEqual(raised.exception.http_status, 404)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_an_explicit_date_without_rows_is_404_and_never_substituted(self, cache):
        """用户点名了 09-07，库里没有 → 404，而不是把 09-08 当结果返回。"""
        from kaipanla.services.read_path import read_sectors

        with self.assertRaises(ApiError) as raised:
            read_sectors(datetime(2026, 9, 7).date())

        self.assertEqual(raised.exception.http_status, 404)
        self.assertEqual(raised.exception.code, ErrorCode.DATA_NOT_AVAILABLE)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_an_explicit_date_is_never_reported_as_stale(self, cache):
        """用户自己点了 09-08，那 09-08 就是他要的那天，不是"旧数据"。"""
        from kaipanla.services.read_path import read_sectors

        result = read_sectors(self.trade_date)

        self.assertEqual(result.business_date, self.trade_date)
        self.assertFalse(result.stale)
        self.assertEqual(result.warnings, ())

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_a_new_collected_slot_is_not_served_from_the_previous_slot_cache(
        self, cache_factory
    ):
        """缓存身份 = 当天最新的采集槽：新槽一到，键就变，绝不会命中旧的载荷。"""
        from kaipanla.services.read_path import read_intraday

        cache_factory.return_value = self.cache
        # 槽位必须是标准交易槽 —— `query_intraday` 的时轴只有 09:30–15:00 的
        # 50 个五分区，落在别处（如 15:05）的行读路径根本不看。
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').all().delete()
        store(self.trade_date, hour=14, minute=50)  # 1 亿
        first_written_at = timezone.now() - timedelta(days=30)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').update(
            created_at=first_written_at
        )

        first = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)
        second = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)
        store(self.trade_date, hour=14, minute=55, net_inflow='500000000')  # 5 亿
        slot_written_at = timezone.now() - timedelta(days=3)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').filter(
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 14, 55))
        ).update(created_at=slot_written_at)
        third = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(first.source, 'database')
        self.assertEqual(second.source, 'cache')
        self.assertEqual(third.source, 'database')
        self.assertEqual(third.cache_identity, 'kaipanla:2026-09-08T14:55')
        self.assertEqual(third.data['series'][0]['latest_net_inflow'], 5.0)
        # 时间戳每次请求都从库里重取（缓存只存载荷、不存信封），命中缓存也不例外：
        # 漏传的表现是"页面刷过一次之后，胶囊上的时刻就没了"。
        self.assertEqual(first.data_updated_at, first_written_at)
        self.assertEqual(second.data_updated_at, first_written_at)
        self.assertEqual(third.data_updated_at, slot_written_at)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_the_response_reports_when_the_stored_snapshot_was_written(self, cache):
        """「更新于」取的是**库里这批快照的写入时刻**，不是这次请求的时刻。

        快照落库后一直躺在库里，页面随时打开，两者可以差几个小时。这里把 setUp 里的
        那一槽标成三十天前写的 —— 哪天它退化成 `timezone.now()`，这条立刻挂。
        """
        from kaipanla.services.read_path import read_intraday

        written_at = timezone.now() - timedelta(days=30)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').update(
            created_at=written_at
        )

        result = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(result.source, 'database')
        self.assertEqual(result.data_updated_at, written_at)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_read_dates_reports_when_the_newest_day_was_written(self, cache):
        """日期清单的信封也带时刻：它说的是"库里最新那批数据是什么时候写的"。"""
        from kaipanla.services.read_path import read_dates

        written_at = timezone.now() - timedelta(days=7)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').update(
            created_at=written_at
        )

        result = read_dates()

        self.assertEqual(result.data_updated_at, written_at)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_read_dates_lists_every_stored_day_newest_first(self, cache):
        from kaipanla.services.read_path import read_dates

        store(datetime(2026, 9, 9).date(), code='B', name='乙行业')

        result = read_dates()

        self.assertEqual(result.data['dates'], ['2026-09-09', '2026-09-08'])
        self.assertEqual(result.business_date, datetime(2026, 9, 9).date())

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_read_dates_without_any_snapshot_is_404(self, cache):
        from kaipanla.services.read_path import read_dates

        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').all().delete()

        with self.assertRaises(ApiError) as raised:
            read_dates()

        self.assertEqual(raised.exception.http_status, 404)
