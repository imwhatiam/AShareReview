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

    def test_partial_run_keeps_the_previous_last_success_at(self):
        """部分成功不能把"最近一次完整成功是什么时候"抹成 NULL。

        `ModuleRunStatus` 每个数据集只有一行、就地更新，运维只能从它回答这个
        问题；`DataVersion.last_success_at` 可以在 PARTIAL 行上为 NULL，是因为
        每次运行都有自己的行（读路径也按它排序取最新版本）—— 两者是"每个数据集"
        与"每个版本"的区别，不是同一件事的两种写法。
        """
        from core.models import DataVersion, ModuleRunStatus
        from core.services.publication import begin_publication, finish_publication

        complete_run = begin_publication(
            module_id='core',
            dataset_key='stock_daily_prices',
            business_date=date(2026, 9, 4),
            expected_record_count=1,
        )
        finish_publication(complete_run, actual_record_count=1, missing_record_count=0)
        recorded = ModuleRunStatus.objects.get(
            module_id='core', dataset_key='stock_daily_prices'
        ).last_success_at
        self.assertIsNotNone(recorded)

        partial_run = begin_publication(
            module_id='core',
            dataset_key='stock_daily_prices',
            business_date=date(2026, 9, 7),
            expected_record_count=2,
        )
        version = finish_publication(
            partial_run, actual_record_count=1, missing_record_count=1
        )

        run_status = ModuleRunStatus.objects.get(
            module_id='core', dataset_key='stock_daily_prices'
        )
        self.assertEqual(version.status, DataVersion.Status.PARTIAL)
        self.assertEqual(run_status.completeness, DataVersion.Status.PARTIAL)
        self.assertEqual(run_status.last_success_at, recorded)

    def test_only_the_kept_and_current_versions_are_touched_when_superseding(self):
        """退休只针对"同数据集同业务日"的已发布版本，且不动状态与别的日期。"""
        from core.models import DataVersion
        from core.services.publication import supersede_previous_versions

        business_date = date(2026, 9, 4)
        old = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-v1',
            business_date=business_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=5,
            actual_record_count=5,
        )
        partial = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-v2',
            business_date=business_date,
            status=DataVersion.Status.PARTIAL,
            expected_record_count=5,
            actual_record_count=3,
            missing_record_count=2,
        )
        kept = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-v3',
            business_date=business_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=5,
            actual_record_count=5,
        )
        other_day = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-20260907',
            business_date=date(2026, 9, 7),
            status=DataVersion.Status.COMPLETE,
            expected_record_count=4,
            actual_record_count=4,
        )
        other_dataset = DataVersion.objects.create(
            dataset_key='industry_snapshot',
            version='industries-v1',
            business_date=business_date,
            status=DataVersion.Status.COMPLETE,
            expected_record_count=2,
            actual_record_count=2,
        )
        running = DataVersion.objects.create(
            dataset_key='stock_daily_prices',
            version='prices-running',
            business_date=business_date,
            status=DataVersion.Status.RUNNING,
            expected_record_count=7,
        )

        retired = supersede_previous_versions(
            'stock_daily_prices', business_date, keep_version=kept.version
        )
        self.assertEqual(retired, 2)

        for version in (old, partial):
            version.refresh_from_db()
            self.assertEqual(version.expected_record_count, 0)
            self.assertEqual(version.actual_record_count, 0)
            self.assertEqual(version.missing_record_count, 0)
        # 状态是"那次运行成功了没有"的历史记录，退休不改它。
        old.refresh_from_db()
        partial.refresh_from_db()
        self.assertEqual(old.status, DataVersion.Status.COMPLETE)
        self.assertEqual(partial.status, DataVersion.Status.PARTIAL)

        for version in (kept, other_day, other_dataset, running):
            version.refresh_from_db()
        self.assertEqual((kept.expected_record_count, kept.actual_record_count), (5, 5))
        self.assertEqual((other_day.expected_record_count, other_day.actual_record_count), (4, 4))
        self.assertEqual(
            (other_dataset.expected_record_count, other_dataset.actual_record_count), (2, 2)
        )
        self.assertEqual(running.expected_record_count, 7)
