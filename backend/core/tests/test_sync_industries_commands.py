from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import DataVersion, IndustrySnapshot


class FakeKaipanlaIndustryClient:
    def __init__(self, *, parents=(), children_by_parent=None, stocks_by_child=None, error=None):
        self.parents = tuple(parents)
        self.children_by_parent = children_by_parent or {}
        self.stocks_by_child = stocks_by_child or {}
        self.error = error
        self.child_requests = []
        self.stock_requests = []

    def list_parent_industries(self):
        if self.error:
            raise self.error
        return self.parents

    def list_child_industries(self, parent_code):
        self.child_requests.append(parent_code)
        if self.error:
            raise self.error
        return tuple(self.children_by_parent.get(parent_code, ()))

    def list_stock_codes(self, industry_code):
        self.stock_requests.append(industry_code)
        if self.error:
            raise self.error
        value = self.stocks_by_child.get(industry_code, ())
        if isinstance(value, Exception):
            raise value
        return tuple(value)


class KaipanlaIndustrySnapshotCommandTests(TestCase):
    def test_sync_persists_child_rows_and_deduplicated_parent_stock_codes(self):
        client = FakeKaipanlaIndustryClient(
            parents=(
                {'industry_code': 'P1', 'industry_name': '父行业一'},
                {'industry_code': 'P2', 'industry_name': '父行业二'},
            ),
            children_by_parent={
                'P1': (
                    {'industry_code': 'C1', 'industry_name': '子行业一'},
                    {'industry_code': 'C2', 'industry_name': '子行业二'},
                ),
                'P2': ({'industry_code': 'C3', 'industry_name': '子行业三'},),
            },
            stocks_by_child={
                'C1': ('000001', '000002'),
                'C2': ('000002', '000003'),
                'C3': ('000001',),
            },
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(client.child_requests, ['P1', 'P2'])
        self.assertEqual(client.stock_requests, ['C1', 'C2', 'C3'])
        self.assertEqual(IndustrySnapshot.objects.count(), 5)
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='P1').stock_codes,
            ['000001', '000002', '000003'],
        )
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='P2').stock_codes,
            ['000001'],
        )
        self.assertEqual(
            IndustrySnapshot.objects.get(industry_code='C2').industry_level,
            IndustrySnapshot.Level.CHILD,
        )
        version = DataVersion.objects.get(dataset_key='industry_snapshot')
        self.assertEqual(version.status, DataVersion.Status.COMPLETE)
        self.assertEqual(version.business_date, date.today())
        self.assertEqual(version.expected_record_count, 5)
        self.assertEqual(version.actual_record_count, 5)

    def test_partial_fetch_failure_keeps_previously_published_industry_snapshot(self):
        IndustrySnapshot.objects.create(
            industry_code='OLD',
            industry_name='旧行业',
            industry_level=IndustrySnapshot.Level.PARENT,
            stock_codes=['600000'],
        )
        client = FakeKaipanlaIndustryClient(
            parents=({'industry_code': 'P1', 'industry_name': '父行业一'},),
            children_by_parent={
                'P1': ({'industry_code': 'C1', 'industry_name': '子行业一'},),
            },
            stocks_by_child={'C1': RuntimeError('upstream interrupted')},
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
            parents=({'industry_code': 'P1', 'industry_name': '父行业一'},),
            children_by_parent={
                'P1': ({'industry_code': 'C1', 'industry_name': '子行业一'},),
            },
            stocks_by_child={'C1': ('000001',)},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            output = StringIO()
            call_command('sync_kaipanla_industry_snapshot', '--dry-run', stdout=output)

        self.assertIn('dry-run', output.getvalue())
        self.assertEqual(IndustrySnapshot.objects.count(), 0)
        self.assertEqual(DataVersion.objects.count(), 0)

    def test_parent_without_children_uses_its_own_stock_list_without_creating_duplicate_child(self):
        client = FakeKaipanlaIndustryClient(
            parents=({'industry_code': 'P1', 'industry_name': '父行业一'},),
            children_by_parent={'P1': ()},
            stocks_by_child={'P1': ('000001', '000002')},
        )

        with patch('core.services.sync_industries.KaipanlaIndustryClient', return_value=client):
            call_command('sync_kaipanla_industry_snapshot')

        self.assertEqual(client.stock_requests, ['P1'])
        self.assertEqual(IndustrySnapshot.objects.count(), 1)
        parent = IndustrySnapshot.objects.get(industry_code='P1')
        self.assertEqual(parent.industry_level, IndustrySnapshot.Level.PARENT)
        self.assertEqual(parent.stock_codes, ['000001', '000002'])
