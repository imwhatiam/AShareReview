import json
import os
import socket
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from core.services.locking import DatasetLocked, _lock_path, dataset_lock


def _dead_pid() -> int:
    """Return a PID that is certainly not running on this host."""
    process = subprocess.Popen(['/bin/sh', '-c', 'exit 0'])
    process.wait()
    pid = process.pid
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return pid
    # 极少数情况下该 PID 已被立刻复用；退化为扫描一个空闲 PID。
    for candidate in range(60000, 60100):
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
    raise AssertionError('No free PID found for the stale-lock tests.')


def _write_lock(path: Path, *, pid, host, age_seconds: float = 0.0, raw: str | None = None):
    """Write a lock file directly, optionally backdating it."""
    if raw is None:
        raw = json.dumps({'pid': pid, 'host': host, 'token': 'stale-owner-token'})
    path.write_text(raw, encoding='utf-8')
    if age_seconds:
        timestamp = time.time() - age_seconds
        os.utime(path, (timestamp, timestamp))


class DatasetLockTests(SimpleTestCase):
    def test_second_acquisition_of_same_dataset_is_rejected(self):
        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                with self.assertRaises(DatasetLocked):
                    with dataset_lock('core', 'stock_daily_prices', directory=directory):
                        pass

    def test_different_datasets_do_not_block_each_other(self):
        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                with dataset_lock('core', 'trading_calendar', directory=directory):
                    pass

    def test_lock_file_is_removed_after_the_block(self):
        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                path = _lock_path('core', 'stock_daily_prices', directory)
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())
            # 回收用的隔离文件也不应留下。
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_lock_records_its_holder(self):
        with TemporaryDirectory() as directory:
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                owner = json.loads(
                    _lock_path('core', 'stock_daily_prices', directory).read_text('utf-8')
                )
                self.assertEqual(owner['pid'], os.getpid())
                self.assertEqual(owner['host'], socket.gethostname())
                self.assertTrue(owner['token'])
                self.assertEqual(owner['module_id'], 'core')
                self.assertEqual(owner['dataset_key'], 'stock_daily_prices')


class StaleLockReapingTests(SimpleTestCase):
    """A killed holder must not block its dataset forever (P0-1)."""

    def _path(self, directory):
        return _lock_path('core', 'stock_daily_prices', directory)

    def test_lock_whose_holder_is_dead_on_this_host_is_reaped(self):
        with TemporaryDirectory() as directory:
            _write_lock(self._path(directory), pid=_dead_pid(), host=socket.gethostname())
            with dataset_lock(
                'core', 'stock_daily_prices', directory=directory, stale_after_seconds=0
            ):
                pass
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_lock_held_by_a_live_process_is_never_reaped(self):
        with TemporaryDirectory() as directory:
            # 同主机 + 活着的 PID：即使把阈值设为 0（禁用时间回收）也不能夺锁。
            _write_lock(
                self._path(directory),
                pid=os.getpid(),
                host=socket.gethostname(),
                age_seconds=10 * 24 * 60 * 60,
            )
            with self.assertRaises(DatasetLocked):
                with dataset_lock('core', 'stock_daily_prices', directory=directory):
                    pass

    def test_lock_from_another_host_is_reaped_only_after_the_threshold(self):
        with TemporaryDirectory() as directory:
            _write_lock(
                self._path(directory),
                pid=1,
                host='some-other-host',
                age_seconds=100,
            )
            with self.assertRaises(DatasetLocked):
                with dataset_lock(
                    'core',
                    'stock_daily_prices',
                    directory=directory,
                    stale_after_seconds=600,
                ):
                    pass
            with dataset_lock(
                'core', 'stock_daily_prices', directory=directory, stale_after_seconds=60
            ):
                pass

    def test_corrupt_lock_file_follows_the_age_threshold(self):
        with TemporaryDirectory() as directory:
            _write_lock(
                self._path(directory),
                pid=None,
                host=None,
                raw='{"pid": 123',  # 写了一半就被杀掉
                age_seconds=100,
            )
            with self.assertRaises(DatasetLocked):
                with dataset_lock(
                    'core',
                    'stock_daily_prices',
                    directory=directory,
                    stale_after_seconds=600,
                ):
                    pass
            with dataset_lock(
                'core', 'stock_daily_prices', directory=directory, stale_after_seconds=60
            ):
                pass

    def test_zero_threshold_disables_age_based_reaping(self):
        with TemporaryDirectory() as directory:
            _write_lock(
                self._path(directory),
                pid=1,
                host='some-other-host',
                age_seconds=10 * 24 * 60 * 60,
            )
            with self.assertRaises(DatasetLocked):
                with dataset_lock(
                    'core',
                    'stock_daily_prices',
                    directory=directory,
                    stale_after_seconds=0,
                ):
                    pass

    def test_release_keeps_a_lock_recreated_by_another_owner(self):
        """回收后别人重建的锁，不能被原持有者的 finally 顺手删掉。"""
        with TemporaryDirectory() as directory:
            path = self._path(directory)
            with dataset_lock('core', 'stock_daily_prices', directory=directory):
                _write_lock(path, pid=_dead_pid(), host=socket.gethostname(), raw=json.dumps({
                    'pid': 1,
                    'host': socket.gethostname(),
                    'token': 'a-different-owner-token',
                }))
            self.assertTrue(path.exists())
