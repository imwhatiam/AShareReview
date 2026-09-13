from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.models import DataVersion, IndustrySnapshot, Stock


class FakeKaipanlaIndustryClient:
    def __init__(
        self,
        *,
        industries=(),
        stocks_by_industry=None,
        error=None,
        request_date='2026-09-11',
    ):
        self.industries = tuple(industries)
        self.stocks_by_industry = stocks_by_industry or {}
        self.error = error
        self.request_date = request_date
        self.stock_requests = []

    def list_industries(self):
        if self.error:
            raise self.error
        return self.industries

    def list_stock_codes(self, industry_code):
        self.stock_requests.append(industry_code)
        if self.error:
            raise self.error
        value = self.stocks_by_industry.get(industry_code, ())
        if isinstance(value, Exception):
            raise value
        return tuple(value)


class IndustrySnapshotNormalizationTests(SimpleTestCase):
    def test_empty_stock_list_is_preserved_as_an_empty_list(self):
        from core.services.sync_industries import _normalize_stock_codes

        self.assertEqual(_normalize_stock_codes([], '801058'), [])


class KaipanlaIndustrySnapshotCommandTests(TestCase):
    def setUp(self):
        # 这些用例只覆盖开盘啦快照的规范化与落库。同花顺补全是独立的一段、有自己的
        # 用例，这里替换成空实现，避免每个用例都去请求真实上游。
        patcher = patch(
            'core.services.sync_industries.backfill_missing_industry_stocks',
            return_value=0,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_sync_persists_every_industry_with_its_own_stock_codes(self):
        client = FakeKaipanlaIndustryClient(
            industries=(
                {'industry_code': '881121', 'industry_name': '半导体'},
                {'industry_code': '881270', 'industry_name': '元件'},
            ),
            stocks_by_industry={
                '881121': ('000001', '000002'),
                '881270': ('000002', '000003'),
            },
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(client.stock_requests, ['881121', '881270'])
        self.assertEqual(IndustrySnapshot.objects.count(), 2)
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='881121').stock_codes,
            ['000001', '000002'],
        )
        # 同一股票可以出现在多个行业里，不做单一归属。
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='881270').stock_codes,
            ['000002', '000003'],
        )
        version = DataVersion.objects.get(dataset_key='industry_snapshot')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        # 归属上游实际服务的交易日，而不是运行当天的本地日期。
        self.assertEqual(version.business_date, date(2026, 9, 11))
        self.assertEqual(version.expected_record_count, 2)
        self.assertEqual(version.actual_record_count, 2)

    def test_duplicate_industry_codes_abort_the_snapshot(self):
        client = FakeKaipanlaIndustryClient(
            industries=(
                {'industry_code': '881121', 'industry_name': '半导体'},
                {'industry_code': '881121', 'industry_name': '半导体二'},
            ),
            stocks_by_industry={'881121': ('000001',)},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(IndustrySnapshot.objects.count(), 0)

    def test_partial_fetch_failure_keeps_previously_published_industry_snapshot(self):
        IndustrySnapshot.objects.create(
            industry_code='OLD',
            industry_name='旧行业',
            stock_codes=['600000'],
        )
        client = FakeKaipanlaIndustryClient(
            industries=({'industry_code': '881121', 'industry_name': '半导体'},),
            stocks_by_industry={'881121': RuntimeError('upstream interrupted')},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            with self.assertRaises(CommandError):
                call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(
            list(IndustrySnapshot.objects.values_list('industry_code', flat=True)),
            ['OLD'],
        )
        self.assertEqual(
            DataVersion.objects.get(dataset_key='industry_snapshot').status,
            DataVersion.Status.FAILED,
        )

    def test_dry_run_fetches_snapshot_without_writing_models_or_versions(self):
        client = FakeKaipanlaIndustryClient(
            industries=({'industry_code': '881121', 'industry_name': '半导体'},),
            stocks_by_industry={'881121': ('000001',)},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            output = StringIO()
            call_command('sync_kaipanla_industry_snapshot', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        self.assertIn('2026-09-11', output.getvalue())
        self.assertEqual(IndustrySnapshot.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)

    def test_success_message_reports_the_trading_day_the_snapshot_belongs_to(self):
        client = FakeKaipanlaIndustryClient(
            industries=({'industry_code': '881121', 'industry_name': '半导体'},),
            stocks_by_industry={'881121': ('000001',)},
            request_date='2026-09-11',
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            output = StringIO()
            call_command('sync_kaipanla_industry_snapshot', stdout=output)

        self.assertIn('synchronized 1 industry records for 2026-09-11.', output.getvalue())
        self.assertEqual(
            DataVersion.objects.get(dataset_key='industry_snapshot').business_date,
            date(2026, 9, 11),
        )

    def test_industry_without_members_is_persisted_with_an_empty_stock_list(self):
        # 上游可以合法地返回空成分股（实测 801058）；这不该阻断其他行业发布。
        client = FakeKaipanlaIndustryClient(
            industries=(
                {'industry_code': '801058', 'industry_name': '空行业'},
                {'industry_code': '881121', 'industry_name': '半导体'},
            ),
            stocks_by_industry={'881121': ('000001', '000002')},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(client.stock_requests, ['801058', '881121'])
        self.assertEqual(IndustrySnapshot.objects.count(), 2)
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='801058').stock_codes,
            [],
        )
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='881121').stock_codes,
            ['000001', '000002'],
        )


class FakeHithinkIndustryClient:
    def __init__(self, *, indices=(), constituents_by_code=None):
        self.indices = tuple(indices)
        self.constituents_by_code = constituents_by_code or {}
        self.constituent_requests = []

    def list_industry_indices(self):
        return self.indices

    def list_industry_constituents(self, thscode):
        self.constituent_requests.append(thscode)
        return tuple(self.constituents_by_code.get(thscode, ()))


class IndustrySnapshotHithinkBackfillWiringTests(TestCase):
    def test_sync_persists_backfilled_members_and_reports_how_many_it_added(self):
        from core.integrations.hithink.contracts import HithinkIndustryIndex

        Stock.objects.create(
            thscode='920012.BJ',
            stock_code='920012',
            stock_name='北交所甲',
            exchange=Stock.Exchange.BSE,
        )
        Stock.objects.create(
            thscode='600000.SH',
            stock_code='600000',
            stock_name='浦发银行',
            exchange=Stock.Exchange.SSE,
        )
        kaipanla = FakeKaipanlaIndustryClient(
            industries=({'industry_code': '881121', 'industry_name': '半导体'},),
            stocks_by_industry={'881121': ('600000',)},
        )
        hithink = FakeHithinkIndustryClient(
            indices=(HithinkIndustryIndex(
                thscode='881121.TI',
                industry_code='881121',
                industry_name='半导体',
            ),),
            constituents_by_code={'881121.TI': ('600000', '920012')},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=kaipanla):
            with patch('core.services.industry_backfill.HithinkClient', return_value=hithink):
                output = StringIO()
                call_command('sync_kaipanla_industry_snapshot', stdout=output)

        self.assertEqual(hithink.constituent_requests, ['881121.TI'])
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='881121').stock_codes,
            ['600000', '920012'],
        )
        self.assertIn(
            'synchronized 1 industry records for 2026-09-11.',
            output.getvalue(),
        )
        self.assertIn('Backfilled 1 stock assignments', output.getvalue())
