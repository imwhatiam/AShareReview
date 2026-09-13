"""Small cross-process filesystem locks for bounded dataset work.

锁的健壮性要求比"能互斥"更高一层：**进程被 SIGKILL / OOM / cron 超时杀掉时
``finally`` 不会执行**，锁文件会永久残留，此后该数据集的所有采集命令与按需生成
都会一直失败（``DatasetLocked``），只能人工删文件才能恢复。所以每把锁都写入持有者
身份（主机名 + PID + 唯一令牌 + 创建时间），获取失败时先判断旧锁是否"陈旧"。

陈旧判定（宁可漏判也不误判 —— 误回收一把活锁会造成两个进程同时写同一数据集）：

1. 旧锁与当前进程**同主机**且 PID **已不存在** → 持有者已死，陈旧。
2. 旧锁文件（或它的持有者记录）**超过 ``LOCK_STALE_SECONDS``** → 陈旧。
   这是跨主机、主机名缺失、锁文件损坏或只写了一半等情况的唯一兜底。
3. 同主机且 PID **仍存活** → 一律视为有效，**不按时间回收**。宁可由运维介入，
   也不冒双写的风险。

回收必须原子：用 ``os.replace`` 把旧锁改名成独占的隔离名，只有改名成功的进程
获得回收权（两个进程同时判定为陈旧时也只有一个能赢），随后它删除隔离文件并重试
创建。释放时校验令牌，避免把自己已不持有的锁删掉。
"""

import hashlib
import json
import logging
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from backend.env import get_int_setting, get_path_setting
from core.logging import log_event

logger = logging.getLogger('core.locking')

# 默认 6 小时：远大于任何单次命令或请求内生成的实际耗时量级（最长的全量行业快照
# 约 4 分钟），所以正常运行绝不会因为超龄而被误回收。
DEFAULT_STALE_AFTER_SECONDS = 6 * 60 * 60

_REAP_SUFFIX = '.reaping'


class DatasetLocked(RuntimeError):
    """Raised when another process already owns a dataset lock."""


class DatasetBusy(RuntimeError):
    """Raised by a read path when the dataset lock is held and nothing can be served.

    ``DatasetLocked`` only says "I could not take the lock" and is raised inside
    the write/generate path. The read path has a second decision to make, and all
    four business modules must make it the same way:

    - an older stored result exists → serve it and flag ``stale`` (spec §5.8a
      "其余请求立刻返回旧数据或 202");
    - nothing stored at all → ``409 SYNC_IN_PROGRESS`` + ``preparation.state``
      ``syncing`` (spec §5.7 "同一数据集已有互斥任务运行").

    So the read path translates ``DatasetLocked`` into this type, lets the
    stale-fallback logic run, and lets the view answer 409 only when that logic
    had nothing to fall back to. Before this, ``kaipanla`` answered 409 while the
    other three answered 202/404 for the very same situation.
    """


def _lock_path(module_id: str, dataset_key: str, directory: str | Path | None) -> Path:
    root = Path(directory) if directory is not None else get_path_setting('LOCK_DIRECTORY')
    identity = f'{module_id}:{dataset_key}'.encode('utf-8')
    return root / f'{hashlib.sha256(identity).hexdigest()}.lock'


def _stale_after_seconds() -> int:
    """Resolve the age threshold; ``<= 0`` disables age-based reaping entirely."""
    return get_int_setting('LOCK_STALE_SECONDS', DEFAULT_STALE_AFTER_SECONDS)


def _read_owner(path: Path) -> dict | None:
    """Return the parsed holder record, or ``None`` when it is missing or corrupt."""
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        return None
    try:
        owner = json.loads(raw)
    except ValueError:
        return None
    return owner if isinstance(owner, dict) else None


def _age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def _process_is_alive(pid: int) -> bool:
    """Same-host liveness probe; anything undecidable counts as "still alive"."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # 进程存在但不属于当前用户（或其他无法判定的情况）——按存活处理。
        return True
    return True


def _lock_is_stale(path: Path, *, stale_after: int) -> bool:
    owner = _read_owner(path)
    if owner is not None:
        pid = owner.get('pid')
        host = owner.get('host')
        if isinstance(pid, int) and pid > 0 and host == socket.gethostname():
            return not _process_is_alive(pid)
    if stale_after <= 0:
        # 只允许"同主机且持有者已死"这一种回收条件。
        return False
    age = _age_seconds(path)
    return age is not None and age >= stale_after


def _reap_stale_lock(
    path: Path,
    *,
    module_id: str,
    dataset_key: str,
    stale_after: int,
) -> bool:
    """Atomically claim the right to remove a stale lock. ``True`` means retry."""
    if not _lock_is_stale(path, stale_after=stale_after):
        return False
    quarantine = path.with_name(f'{path.name}{_REAP_SUFFIX}-{uuid.uuid4().hex}')
    try:
        os.replace(path, quarantine)
    except FileNotFoundError:
        # 别的进程刚回收完，直接重试创建即可。
        return True
    except OSError as error:
        log_event(
            logger,
            'dataset_lock_reap_failed',
            level=logging.WARNING,
            module_id=module_id,
            dataset_key=dataset_key,
            error=error,
        )
        return False

    owner = _read_owner(quarantine) or {}
    quarantine.unlink(missing_ok=True)
    log_event(
        logger,
        'dataset_lock_reaped',
        level=logging.WARNING,
        module_id=module_id,
        dataset_key=dataset_key,
        stale_owner_pid=owner.get('pid'),
        stale_owner_host=owner.get('host'),
        stale_owner_created_at=owner.get('created_at'),
    )
    return True


def _acquire(
    path: Path,
    *,
    module_id: str,
    dataset_key: str,
    stale_after: int,
) -> str:
    """Create the lock file exclusively, reaping at most one stale lock. Returns the token."""
    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            if attempt == 0 and _reap_stale_lock(
                path,
                module_id=module_id,
                dataset_key=dataset_key,
                stale_after=stale_after,
            ):
                continue
            raise DatasetLocked(f'{module_id}:{dataset_key} is already running.') from error

        token = uuid.uuid4().hex
        owner = {
            'pid': os.getpid(),
            'host': socket.gethostname(),
            'token': token,
            'module_id': module_id,
            'dataset_key': dataset_key,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        with os.fdopen(descriptor, 'w', encoding='utf-8') as lock_file:
            json.dump(owner, lock_file)
        return token
    raise DatasetLocked(f'{module_id}:{dataset_key} is already running.')


def _release(path: Path, token: str) -> None:
    """Remove the lock only while we still own it.

    如果这把锁曾被判为陈旧并被别人回收、又被别人重新创建，这里再删就等于放掉了
    一把自己并不持有的锁。
    """
    owner = _read_owner(path)
    if owner is not None and owner.get('token') != token:
        log_event(
            logger,
            'dataset_lock_release_skipped',
            level=logging.WARNING,
            lock_path=str(path),
        )
        return
    path.unlink(missing_ok=True)


@contextmanager
def dataset_lock(
    module_id: str,
    dataset_key: str,
    directory: str | Path | None = None,
    *,
    stale_after_seconds: int | None = None,
) -> Iterator[None]:
    """Acquire a non-blocking lock, reaping one stale lock, and release our own."""
    path = _lock_path(module_id, dataset_key, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    stale_after = (
        _stale_after_seconds() if stale_after_seconds is None else stale_after_seconds
    )
    token = _acquire(
        path,
        module_id=module_id,
        dataset_key=dataset_key,
        stale_after=stale_after,
    )
    try:
        yield
    finally:
        _release(path, token)
