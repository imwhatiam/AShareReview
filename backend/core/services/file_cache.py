"""Bounded, atomic JSON file cache for API response data."""

import json
import logging
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from backend.env import get_bool_setting, get_path_setting, get_required_setting
from core.api.errors import ErrorCode
from core.logging import log_event
from core.services.cache_keys import CacheKey


logger = logging.getLogger(__name__)


class CachePayloadTooLarge(ValueError):
    """Raised before an oversized cache response reaches disk."""


class FileCache:
    def __init__(self, directory: Path, ttl_seconds: int, max_bytes: int):
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes

    def path_for(self, key: CacheKey) -> Path:
        return self.directory / key.module_id / key.filename

    def get(self, key: CacheKey, data_version: str, now: float | None = None) -> Any | None:
        """Return the cached payload, or ``None`` for any kind of miss.

        A *corrupt* entry is still a miss — the caller recomputes it from SQLite
        and rewrites the file, so it self-heals and must not turn into a failed
        page. It is, however, no longer indistinguishable from an ordinary miss:
        the ``cache_entry_corrupted`` event carries ``error_code=CACHE_CORRUPTED``
        so "缓存从来没命中过" and "缓存文件坏了" can be told apart in the log.
        """
        path = self.path_for(key)
        try:
            raw = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return None
        except OSError as error:
            self._report_corruption(path, reason=f'unreadable:{error.__class__.__name__}')
            return None
        try:
            payload = json.loads(raw)
            if payload['data_version'] != data_version:
                return None
            if payload['expires_at'] <= (time.time() if now is None else now):
                return None
            return payload['data']
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self._report_corruption(path, reason=error.__class__.__name__)
            return None

    @staticmethod
    def _report_corruption(path: Path, *, reason: str) -> None:
        log_event(
            logger,
            'cache_entry_corrupted',
            level=logging.WARNING,
            path=str(path),
            reason=reason,
            error_code=ErrorCode.CACHE_CORRUPTED.value,
        )

    def set(
        self,
        key: CacheKey,
        data: Any,
        data_version: str,
        now: float | None = None,
    ) -> None:
        """Write the payload's **JSON view** under ``key``, atomically.

        The encoder is Django's own response encoder, on purpose: the cache stores
        exactly what the client would receive, so a hit and a miss cannot differ on
        the wire (``Decimal`` → string, ``datetime`` → ISO-8601, both like the
        response body). The encoder also rejects anything it cannot represent
        instead of stringifying it — the previous ``default=str`` silently turned
        an unexpected object into ``"<... object at 0x...>"`` and hid the mistake
        until someone read the file.

        Note the consequence for in-process callers: a payload built from
        ``DecimalField`` values comes back as **strings** on a cache hit but as
        ``Decimal`` on a miss. Treat cached payloads as transport data — never do
        arithmetic on a field read out of ``get()``.
        """
        created_at = time.time() if now is None else now
        content = json.dumps(
            {
                'created_at': created_at,
                'expires_at': created_at + self.ttl_seconds,
                'data_version': data_version,
                'data': data,
            },
            ensure_ascii=False,
            separators=(',', ':'),
            cls=DjangoJSONEncoder,
        ).encode('utf-8')
        if len(content) > self.max_bytes:
            raise CachePayloadTooLarge(
                f'Cache payload is {len(content)} bytes, exceeds {self.max_bytes} bytes.'
            )
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode='wb', dir=path.parent, prefix='.tmp-', delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def invalidate_module(self, module_id: str) -> None:
        module_directory = self.directory / module_id
        if not module_directory.is_dir():
            return
        for path in module_directory.glob('*.json'):
            path.unlink(missing_ok=True)
        try:
            module_directory.rmdir()
        except OSError:
            pass


def default_file_cache() -> FileCache | None:
    if not get_bool_setting('FILE_CACHE_ENABLED', default=False):
        return None
    return FileCache(
        get_path_setting('FILE_CACHE_DIRECTORY'),
        ttl_seconds=int(get_required_setting('FILE_CACHE_TTL_SECONDS')),
        max_bytes=int(get_required_setting('FILE_CACHE_MAX_BYTES')),
    )
