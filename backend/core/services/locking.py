"""Small cross-process filesystem locks for bounded dataset work."""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.env import get_path_setting


class DatasetLocked(RuntimeError):
    """Raised when another process already owns a dataset lock."""


def _lock_path(module_id: str, dataset_key: str, directory: str | Path | None) -> Path:
    root = Path(directory) if directory is not None else get_path_setting('LOCK_DIRECTORY')
    identity = f'{module_id}:{dataset_key}'.encode('utf-8')
    return root / f'{hashlib.sha256(identity).hexdigest()}.lock'


@contextmanager
def dataset_lock(
    module_id: str, dataset_key: str, directory: str | Path | None = None
) -> Iterator[None]:
    """Acquire a non-blocking lock and always remove the owned lock file."""
    path = _lock_path(module_id, dataset_key, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise DatasetLocked(f'{module_id}:{dataset_key} is already running.') from error
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as lock_file:
            lock_file.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)
