"""Bounded, atomic JSON file cache for API response data."""

import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from backend.env import get_bool_setting, get_path_setting, get_required_setting
from core.services.cache_keys import CacheKey


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
        path = self.path_for(key)
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if payload['data_version'] != data_version:
                return None
            if payload['expires_at'] <= (time.time() if now is None else now):
                return None
            return payload['data']
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError, TypeError):
            return None

    def set(
        self,
        key: CacheKey,
        data: Any,
        data_version: str,
        now: float | None = None,
    ) -> None:
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
            default=str,
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
