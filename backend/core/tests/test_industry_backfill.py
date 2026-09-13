from unittest.mock import patch

from django.test import TestCase

from core.integrations.hithink.contracts import HithinkIndustryIndex
from core.models import Stock


class FakeHithinkIndustryClient:
    def __init__(self, *, indices=(), constituents_by_code=None, error=None):
        self.indices = tuple(indices)
        self.constituents_by_code = constituents_by_code or {}
        self.error = error
        self.constituent_requests = []

    def list_industry_indices(self):
        if self.error:
            raise self.error
        return self.indices

    def list_industry_constituents(self, thscode):
        self.constituent_requests.append(thscode)
        if self.error:
            raise self.error
        value = self.constituents_by_code.get(thscode, ())
        if isinstance(value, Exception):
            raise value
        return tuple(value)


def _industry_record(industry_code, industry_name, stock_codes):
    return {
        'industry_code': industry_code,
        'industry_name': industry_name,
        'stock_codes': sorted(stock_codes),
    }


def _industry(thscode, name):
    return HithinkIndustryIndex(
        thscode=thscode,
        industry_code=thscode.split('.', 1)[0],
        industry_name=name,
    )


class IndustryBackfillTests(TestCase):
    def setUp(self):
        for stock_code, stock_name in (
            ('600000', '浦发银行'),
            ('600001', '邯郸钢铁'),
            ('920012', '北交所甲'),
        ):
            Stock.objects.create(
                thscode=f'{stock_code}.SH',
                stock_code=stock_code,
                stock_name=stock_name,
                exchange=Stock.Exchange.BSE if stock_code.startswith('92') else Stock.Exchange.SSE,
            )

    def _backfill(self, records, client):
        from core.services.industry_backfill import backfill_missing_industry_stocks

        return backfill_missing_industry_stocks(records, client=client)

    def test_adds_only_the_members_the_kaipanla_snapshot_is_missing(self):
        records = [_industry_record('881121', '半导体', ['600000'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': ('600000', '600001', '920012')},
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 2)
        self.assertEqual(records[0]['stock_codes'], ['600000', '600001', '920012'])
        self.assertEqual(client.constituent_requests, ['881121.TI'])

    def test_members_unknown_to_the_local_stock_master_are_ignored(self):
        records = [_industry_record('881121', '半导体', ['600000'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': ('600000', '999999')},
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 0)
        self.assertEqual(records[0]['stock_codes'], ['600000'])

    def test_kaipanla_members_are_never_removed(self):
        records = [_industry_record('881121', '半导体', ['600000', '600001'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': ('600000',)},
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 0)
        self.assertEqual(records[0]['stock_codes'], ['600000', '600001'])

    def test_industry_codes_absent_from_hithink_are_skipped(self):
        # 开盘啦比同花顺多出 14 个旧代码（如 881120 电力设备），它们没有对应的
        # 同花顺指数，不能去请求，否则会拿到空成分股或上游错误。
        records = [
            _industry_record('881120', '电力设备', ['600000']),
            _industry_record('881121', '半导体', ['600000']),
        ]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': ('920012',)},
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 1)
        self.assertEqual(client.constituent_requests, ['881121.TI'])
        self.assertEqual(records[0]['stock_codes'], ['600000'])
        self.assertEqual(records[1]['stock_codes'], ['600000', '920012'])

    def test_hithink_indices_absent_from_the_kaipanla_snapshot_are_never_requested(self):
        # 同花顺目录里还有更细的 884xxx 行业，开盘啦的行业快照里没有这些代码；
        # 补进来只会制造重叠，所以只按开盘啦已有的代码去请求。
        records = [_industry_record('881121', '半导体', ['600000'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'), _industry('884096.TI', '光学元件')),
            constituents_by_code={'884096.TI': ('920012',)},
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 0)
        self.assertEqual(client.constituent_requests, ['881121.TI'])
        self.assertEqual(records[0]['stock_codes'], ['600000'])

    def test_backfill_can_be_turned_off_by_setting(self):
        records = [_industry_record('881121', '半导体', ['600000'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': ('920012',)},
        )

        with patch.dict('os.environ', {'HITHINK_INDUSTRY_BACKFILL_ENABLED': '0'}):
            added = self._backfill(records, client)

        self.assertEqual(added, 0)
        self.assertEqual(client.constituent_requests, [])
        self.assertEqual(records[0]['stock_codes'], ['600000'])

    def test_upstream_failure_propagates_instead_of_publishing_a_partial_snapshot(self):
        records = [_industry_record('881121', '半导体', ['600000'])]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'),),
            constituents_by_code={'881121.TI': RuntimeError('upstream interrupted')},
        )

        with self.assertRaises(RuntimeError):
            self._backfill(records, client)

    def test_two_industries_sharing_one_new_member_are_counted_once(self):
        records = [
            _industry_record('881121', '半导体', ['600000']),
            _industry_record('881270', '元件', ['600001']),
        ]
        client = FakeHithinkIndustryClient(
            indices=(_industry('881121.TI', '半导体'), _industry('881270.TI', '元件')),
            constituents_by_code={
                '881121.TI': ('920012',),
                '881270.TI': ('920012',),
            },
        )

        added = self._backfill(records, client)

        self.assertEqual(added, 1)
        self.assertEqual(records[0]['stock_codes'], ['600000', '920012'])
        self.assertEqual(records[1]['stock_codes'], ['600001', '920012'])
