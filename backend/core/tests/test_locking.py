from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class DatasetLockTests(SimpleTestCase):
    def test_second_acquisition_of_same_dataset_is_rejected(self):
        from core.services.locking import DatasetLocked, dataset_lock

        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                with self.assertRaises(DatasetLocked):
                    with dataset_lock('core', 'stock_daily_prices', directory=directory):
                        pass

    def test_different_datasets_do_not_block_each_other(self):
        from core.services.locking import dataset_lock

        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                with dataset_lock('core', 'trading_calendar', directory=directory):
                    pass
