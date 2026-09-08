from datetime import date

from django.test import TestCase


class PublicationTests(TestCase):
    def _create_complete_version(self, version):
        from core.models import DataVersion

        return DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version=version,
            business_date=date(2026, 9, 4),
            status=DataVersion.Status.COMPLETE,
            expected_record_count=1,
            actual_record_count=1,
        )

    def test_incomplete_run_is_not_published_as_complete(self):
        from core.models import DataVersion, ModuleRunStatus
        from core.services.publication import begin_publication, finish_publication

        self._create_complete_version('prices-20260904-v1')
        run = begin_publication(
            module_id='core',
            dataset_key='stock_daily_prices',
            business_date=date(2026, 9, 7),
            expected_record_count=2,
        )

        version = finish_publication(run, actual_record_count=1, missing_record_count=1)
        run_status = ModuleRunStatus.objects.get(
            module_id='core', dataset_key='stock_daily_prices'
        )

        self.assertEqual(version.status, DataVersion.Status.PARTIAL)
        self.assertEqual(
            DataVersion.objects.filter(
                dataset_key='stock_daily_prices', status=DataVersion.Status.COMPLETE
            ).count(),
            1,
        )
        self.assertEqual(run_status.status, ModuleRunStatus.Status.SUCCESS)
        self.assertEqual(run_status.completeness, DataVersion.Status.PARTIAL)
        self.assertTrue(run_status.serving_stale)

    def test_failed_write_keeps_previous_complete_version_and_increments_failure_count(self):
        from core.models import DataVersion, ModuleRunStatus
        from core.services.publication import begin_publication, publish_with_writer

        self._create_complete_version('prices-20260904-v1')
        run = begin_publication(
            module_id='core',
            dataset_key='stock_daily_prices',
            business_date=date(2026, 9, 7),
            expected_record_count=1,
        )

        def write_then_fail():
            raise RuntimeError('write failed')

        with self.assertRaisesRegex(RuntimeError, 'write failed'):
            publish_with_writer(
                run,
                write_then_fail,
                actual_record_count=0,
                missing_record_count=1,
            )

        failed_version = DataVersion.objects.get(version=run.version)
        run_status = ModuleRunStatus.objects.get(
            module_id='core', dataset_key='stock_daily_prices'
        )
        self.assertEqual(failed_version.status, DataVersion.Status.FAILED)
        self.assertEqual(
            DataVersion.objects.filter(
                dataset_key='stock_daily_prices', status=DataVersion.Status.COMPLETE
            ).count(),
            1,
        )
        self.assertEqual(run_status.status, ModuleRunStatus.Status.FAILED)
        self.assertEqual(run_status.consecutive_failure_count, 1)

    def test_complete_run_resets_failure_count(self):
        from core.models import ModuleRunStatus
        from core.services.publication import begin_publication, finish_publication

        ModuleRunStatus.objects.create(
            module_id='core',
            dataset_key='stock_daily_prices',
            status=ModuleRunStatus.Status.FAILED,
            completeness='failed',
            consecutive_failure_count=3,
        )
        run = begin_publication(
            module_id='core',
            dataset_key='stock_daily_prices',
            business_date=date(2026, 9, 7),
            expected_record_count=1,
        )

        finish_publication(run, actual_record_count=1, missing_record_count=0)

        run_status = ModuleRunStatus.objects.get(
            module_id='core', dataset_key='stock_daily_prices'
        )
        self.assertEqual(run_status.status, ModuleRunStatus.Status.SUCCESS)
        self.assertEqual(run_status.completeness, 'complete')
        self.assertEqual(run_status.consecutive_failure_count, 0)
        self.assertFalse(run_status.serving_stale)
