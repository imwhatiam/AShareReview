from datetime import datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.api.errors import ErrorCode
from core.models import DataVersion, TradingDay
from core.services.file_cache import FileCache
from core.services.cache_keys import build_cache_key
from kaipanla.models import KaipanlaSectorFundFlowSnapshot
from kaipanla.services.read_path import RepairOutcome


class KaipanlaReadFallbackTests(TestCase):
    databases = {'default', 'kaipanla'}

    def setUp(self):
        self.trade_date = datetime(2026, 9, 8).date()
        TradingDay.objects.create(trade_date=self.trade_date)
        KaipanlaSectorFundFlowSnapshot.objects.using('kaipanla').create(
            sector_code='A',
            sector_name='甲行业',
            trade_date=self.trade_date,
            snapshot_time=timezone.make_aware(datetime(2026, 9, 8, 15, 0)),
            main_net_inflow=Decimal('100000000'),
            source_data_version='kaipanla-fallback-version',
            source_batch_id='published-snapshot',
        )
        DataVersion.objects.create(
            dataset_key='kaipanla_sector_fund_flow',
            version='kaipanla-fallback-version',
            business_date=self.trade_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )
        self.cache_directory = TemporaryDirectory()
        self.cache = FileCache(self.cache_directory.name, ttl_seconds=300, max_bytes=1_000_000)
        self.addCleanup(self.cache_directory.cleanup)

    def patch_now(self, *parts):
        """修复只服务当天，因此把"现在"固定在交易日盘中。"""
        return patch(
            'django.utils.timezone.now',
            return_value=timezone.make_aware(datetime(*parts)),
        )

    @patch('kaipanla.services.read_path.default_file_cache')
    def test_corrupt_cache_falls_back_to_published_database_data(self, cache_factory):
        from kaipanla.services.read_path import read_intraday

        cache_factory.return_value = self.cache
        key = build_cache_key(
            'kaipanla',
            'sectors/intraday',
            {'date': '2026-09-08', 'inflow_top': 1, 'outflow_top': 1},
            'kaipanla-fallback-version',
        )
        path = self.cache.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not-json', encoding='utf-8')

        result = read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(result.source, 'database')
        self.assertEqual([item['code'] for item in result.data['series']], ['A'])

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch(
        'kaipanla.services.read_path._repair_current_snapshot',
        return_value=RepairOutcome(False),
    )
    def test_missing_current_data_attempts_one_bounded_repair_then_reports_preparing(
        self, repair, can_repair
    ):
        from core.api.errors import ApiError, ErrorCode
        from kaipanla.services.read_path import read_intraday

        DataVersion.objects.all().delete()

        with self.assertRaises(ApiError) as raised:
            read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(raised.exception.code, ErrorCode.DATA_PREPARING)
        self.assertEqual(raised.exception.http_status, 202)
        can_repair.assert_called_once_with(self.trade_date)
        repair.assert_called_once_with(self.trade_date)

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch(
        'kaipanla.services.read_path._repair_current_snapshot',
        return_value=RepairOutcome(False, ErrorCode.UPSTREAM_RATE_LIMITED),
    )
    def test_a_throttled_upstream_answers_503_instead_of_202(self, repair, can_repair):
        """限流是确定性失败：202 会让客户端对着一个正在限流的上游反复重试。"""
        from core.api.errors import ApiError, ErrorCode
        from kaipanla.services.read_path import read_intraday

        DataVersion.objects.all().delete()

        with self.assertRaises(ApiError) as raised:
            read_intraday(self.trade_date, inflow_top=1, outflow_top=1)

        self.assertEqual(raised.exception.code, ErrorCode.UPSTREAM_RATE_LIMITED)
        self.assertEqual(raised.exception.http_status, 503)

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    @patch('kaipanla.services.read_path.latest_complete_stock_price_date')
    def test_default_entry_anchors_on_the_latest_public_daily_price_day(
        self, latest_public, cache
    ):
        """四个页面必须对"最新一天"给出同一个答案（规格 §5.8a）。"""
        from kaipanla.services.read_path import read_sectors

        latest_public.return_value = self.trade_date

        result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertFalse(result.stale)
        self.assertEqual(result.warnings, ())

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=False)
    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    @patch('kaipanla.services.read_path.latest_complete_stock_price_date')
    def test_an_anchor_day_without_a_snapshot_serves_the_newest_one_as_stale(
        self, latest_public, cache, can_repair
    ):
        """锚定日还没有快照 → 退回最近一次快照，并如实标 stale（规格 §5.8.6）。"""
        from kaipanla.services.read_path import read_sectors

        latest_public.return_value = datetime(2026, 9, 9).date()

        result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertIn('最近一次可用快照', result.warnings[0])

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch(
        'kaipanla.services.read_path._repair_current_snapshot',
        return_value=RepairOutcome(False, ErrorCode.UPSTREAM_RATE_LIMITED),
    )
    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    @patch('kaipanla.services.read_path.latest_complete_stock_price_date')
    def test_a_pending_repair_is_not_masked_by_old_data(
        self, latest_public, cache, repair, can_repair
    ):
        """有旧数据也不该把"上游在限流"伪装成"数据有点旧"：状态必须还能看见。"""
        from core.api.errors import ApiError
        from kaipanla.services.read_path import read_sectors

        latest_public.return_value = datetime(2026, 9, 9).date()

        with self.assertRaises(ApiError) as raised:
            read_sectors()

        self.assertEqual(raised.exception.code, ErrorCode.UPSTREAM_RATE_LIMITED)
        self.assertEqual(raised.exception.http_status, 503)

    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    @patch('kaipanla.services.read_path._repair_current_snapshot')
    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    @patch('kaipanla.services.read_path.latest_complete_stock_price_date')
    def test_a_busy_dataset_serves_the_old_snapshot_as_stale(
        self, latest_public, cache, repair, can_repair
    ):
        """数据集被别的任务占用但还有旧快照：返回旧快照并标 stale，而不是 409。

        规格 §5.8a："其余请求立刻返回旧数据或 202"。四个业务模块现在都对占用给出
        同一个答案，只有"连旧数据都没有"时才升格成 §5.7 的 409。
        """
        from core.services.locking import DatasetBusy
        from kaipanla.services.read_path import read_sectors

        latest_public.return_value = datetime(2026, 9, 9).date()
        repair.side_effect = DatasetBusy(
            'kaipanla:kaipanla_sector_fund_flow is already running.'
        )

        result = read_sectors()

        self.assertEqual(result.business_date, self.trade_date)
        self.assertTrue(result.stale)
        self.assertIn('最近一次可用快照', result.warnings[0])

    @patch('kaipanla.services.read_path.default_file_cache', return_value=None)
    def test_an_explicit_date_is_never_reported_as_stale(self, cache):
        """用户自己点了 09-08，那 09-08 就是他要的那天，不是"旧数据"。"""
        from kaipanla.services.read_path import read_sectors

        result = read_sectors(self.trade_date)

        self.assertEqual(result.business_date, self.trade_date)
        self.assertFalse(result.stale)
        self.assertEqual(result.warnings, ())

    def test_the_repair_row_guard_is_a_constant_that_one_page_cannot_reach(self):
        """行数闸门是常量，不是可运维旋钮。

        一次修复只取一页，而上游单页硬上限就是 ``MAX_PAGE_SIZE``，所以正常永远
        到不了闸门。它以前是 `.env` 里的 ``REMOTE_REPAIR_MAX_ROWS=1000``：调它
        没有任何效果，却和两个真旋钮并列出现在 `.env` 和运维文档里。常量化的
        同时保留判断，是因为它仍要挡住"上游无视 st 硬塞更多行"。
        """
        from kaipanla.services.client import MAX_PAGE_SIZE
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
        from kaipanla.services.parser import KaipanlaSectorFundFlowRow
        from kaipanla.services.read_path import REPAIR_MAX_ROWS, _repair_discard_reason

        def fetch_result(row_count):
            rows = tuple(
                KaipanlaSectorFundFlowRow(
                    sector_code=f'BK{index:03d}',
                    sector_name=f'行业{index}',
                    change_pct=None,
                    main_net_inflow=Decimal('1'),
                    main_buy=None,
                    main_sell=None,
                    large_order_net_inflow=None,
                    volume_ratio=None,
                    turnover_amount=None,
                    float_market_cap=None,
                    total_market_cap=None,
                )
                for index in range(row_count)
            )
            return KaipanlaSectorFundFlowFetchResult(
                rows=rows,
                is_complete=True,
                expected_page_count=1,
                completed_page_count=1,
                failed_page_offsets=(),
                source_timestamp=None,
                source_trade_date='2026-09-08',
            )

        # 闸门上限必须与上游的单页上限同源，否则"一页不可能触顶"这个结论就是假的。
        self.assertEqual(REPAIR_MAX_ROWS, MAX_PAGE_SIZE)

        self.assertIsNone(
            _repair_discard_reason(
                fetch_result=fetch_result(REPAIR_MAX_ROWS),
                elapsed_seconds=0.5,
                hard_timeout=5,
            )
        )
        reason, code = _repair_discard_reason(
            fetch_result=fetch_result(REPAIR_MAX_ROWS + 1),
            elapsed_seconds=0.5,
            hard_timeout=5,
        )
        self.assertEqual(reason, 'row_budget_exceeded')
        self.assertIsNone(code)

    @patch('kaipanla.services.read_path._repair_current_snapshot')
    @patch('kaipanla.services.read_path._can_attempt_repair', return_value=True)
    def test_the_202_answer_carries_the_configured_retry_hint(self, can_repair, repair):
        """202/503 里的 ``retry_after_seconds`` 读的是改名后的重试提示键。

        它不是耗时预算：调大它不会让那次抓取有更多时间（那是
        ``REMOTE_REPAIR_HARD_TIMEOUT_SECONDS`` 的事），所以旧名
        ``REMOTE_REPAIR_TARGET_SECONDS`` 已经废掉。
        """
        from core.api.errors import ApiError
        from kaipanla.services.read_path import _published_version

        DataVersion.objects.all().delete()
        repair.return_value = RepairOutcome(False)

        with patch.dict(
            'os.environ', {'REMOTE_REPAIR_RETRY_AFTER_SECONDS': '9'}, clear=False
        ), self.assertRaises(ApiError) as caught:
            _published_version(None)

        self.assertEqual(caught.exception.code, ErrorCode.DATA_PREPARING)
        self.assertEqual(caught.exception.http_status, 202)
        self.assertEqual(caught.exception.retry_after_seconds, 9)

    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowFetcher')
    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowClient')
    @patch('kaipanla.services.read_path.flow_client_settings')
    def test_remote_repair_uses_one_page_no_retry_and_hard_timeout(
        self, flow_settings, client_class, fetcher_class
    ):
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
        from kaipanla.services.parser import KaipanlaSectorFundFlowRow
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()
        flow_settings.return_value = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid', device_id='device', user_id='', token='',
            version='5.23.0.4', api_version='w44', phone_os_new='1', timeout_seconds=10,
            controller='ZhiShuRanking', action='RealRankingInfo', order='1', ranking_type='1',
            zs_type='7', page_size=80, request_delay_seconds=1.0,
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(KaipanlaSectorFundFlowRow(
                sector_code='B', sector_name='乙行业', change_pct=None,
                main_net_inflow=Decimal('200000000'), main_buy=None, main_sell=None,
                large_order_net_inflow=None, volume_ratio=None, turnover_amount=None,
                float_market_cap=None, total_market_cap=None,
            ),),
            is_complete=True, expected_page_count=1, completed_page_count=1,
            failed_page_offsets=(), source_timestamp=int(
                timezone.make_aware(datetime(2026, 9, 8, 15, 0)).timestamp()
            ), source_trade_date='2026-09-08',
        )

        with self.patch_now(2026, 9, 8, 14, 30):
            outcome = _repair_current_snapshot(self.trade_date)

        self.assertTrue(outcome.published)
        self.assertIsNone(outcome.upstream_code)

        client_settings = client_class.call_args.kwargs['settings']
        self.assertEqual(client_settings.timeout_seconds, 5)
        self.assertEqual(client_settings.request_delay_seconds, 0.0)
        fetcher_class.assert_called_once_with(
            client=client_class.return_value,
            page_size=80,
            max_pages=1,
            max_retries=0,
            retry_delay_seconds=0.0,
        )
        self.assertEqual(
            DataVersion.objects.get(dataset_key='kaipanla_sector_fund_flow').status,
            DataVersion.Status.COMPLETE,
        )

    @patch('kaipanla.services.read_path.dataset_lock', side_effect=Exception('lock unavailable'))
    def test_repair_failure_never_publishes_a_version(self, lock):
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()

        with self.patch_now(2026, 9, 8, 14, 30):
            outcome = _repair_current_snapshot(self.trade_date)

        self.assertFalse(outcome.published)
        # 写侧/锁侧的失败不是"上游不可用"，不能被标成上游错误码。
        self.assertIsNone(outcome.upstream_code)
        self.assertFalse(DataVersion.objects.exists())
        lock.assert_called_once_with('kaipanla', 'kaipanla_sector_fund_flow')

    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowFetcher')
    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowClient')
    @patch('kaipanla.services.read_path.flow_client_settings')
    def test_a_throttled_fetch_is_reported_as_rate_limited(
        self, flow_settings, client_class, fetcher_class
    ):
        """抓取层只给出 failure_kind，读路径负责把它翻成稳定错误码。"""
        from core.api.errors import ErrorCode
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()
        flow_settings.return_value = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid', device_id='device', user_id='', token='',
            version='5.23.0.4', api_version='w44', phone_os_new='1', timeout_seconds=10,
            controller='ZhiShuRanking', action='RealRankingInfo', order='1', ranking_type='1',
            zs_type='4', page_size=80, request_delay_seconds=1.0,
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(), is_complete=False, expected_page_count=1, completed_page_count=0,
            failed_page_offsets=(0,), source_timestamp=None, source_trade_date=None,
            error_summary='The first page failed.', failure_kind='rate_limited',
        )

        with self.patch_now(2026, 9, 8, 14, 30):
            outcome = _repair_current_snapshot(self.trade_date)

        self.assertFalse(outcome.published)
        self.assertEqual(outcome.upstream_code, ErrorCode.UPSTREAM_RATE_LIMITED)
        self.assertFalse(DataVersion.objects.exists())

    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowFetcher')
    @patch('kaipanla.services.read_path.KaipanlaSectorFundFlowClient')
    @patch('kaipanla.services.read_path.flow_client_settings')
    def test_an_incomplete_payload_keeps_the_retryable_preparing_path(
        self, flow_settings, client_class, fetcher_class
    ):
        """上游返回坏结构不该变成 503：换个时刻再来一次确实可能成功。"""
        from kaipanla.services.client import KaipanlaSectorFundFlowClientSettings
        from kaipanla.services.fetcher import KaipanlaSectorFundFlowFetchResult
        from kaipanla.services.read_path import _repair_current_snapshot

        DataVersion.objects.all().delete()
        flow_settings.return_value = KaipanlaSectorFundFlowClientSettings(
            endpoint='https://example.invalid', device_id='device', user_id='', token='',
            version='5.23.0.4', api_version='w44', phone_os_new='1', timeout_seconds=10,
            controller='ZhiShuRanking', action='RealRankingInfo', order='1', ranking_type='1',
            zs_type='4', page_size=80, request_delay_seconds=1.0,
        )
        fetcher_class.return_value.fetch.return_value = KaipanlaSectorFundFlowFetchResult(
            rows=(), is_complete=False, expected_page_count=1, completed_page_count=0,
            failed_page_offsets=(0,), source_timestamp=None, source_trade_date=None,
            error_summary='A required page was empty or malformed.', failure_kind='payload',
        )

        with self.patch_now(2026, 9, 8, 14, 30):
            outcome = _repair_current_snapshot(self.trade_date)

        self.assertFalse(outcome.published)
        self.assertIsNone(outcome.upstream_code)
        self.assertFalse(DataVersion.objects.exists())
