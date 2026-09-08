import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


class FileCacheTests(SimpleTestCase):
    def test_hit_requires_matching_version_and_unexpired_entry(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {'date': '2026-09-08'}, 'v1')
            cache.set(key, {'items': [1]}, data_version='v1', now=100)

            self.assertEqual(cache.get(key, data_version='v1', now=159), {'items': [1]})
            self.assertIsNone(cache.get(key, data_version='v2', now=101))
            self.assertIsNone(cache.get(key, data_version='v1', now=160))

    def test_corrupted_cache_is_a_miss(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')
            path = cache.path_for(key)
            path.parent.mkdir(parents=True)
            path.write_text('{not json', encoding='utf-8')

            self.assertIsNone(cache.get(key, data_version='v1', now=100))

    def test_module_invalidation_does_not_remove_another_modules_files(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            own_key = build_cache_key('kaipanla', 'sectors', {}, 'v1')
            other_key = build_cache_key('eastmoney', 'sectors', {}, 'v1')
            cache.set(own_key, {'source': 'kaipanla'}, data_version='v1', now=100)
            cache.set(other_key, {'source': 'eastmoney'}, data_version='v1', now=100)

            cache.invalidate_module('kaipanla')

            self.assertIsNone(cache.get(own_key, data_version='v1', now=101))
            self.assertEqual(
                cache.get(other_key, data_version='v1', now=101),
                {'source': 'eastmoney'},
            )

    def test_write_is_atomic_and_rejects_oversized_payload(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import CachePayloadTooLarge, FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=100)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')

            with self.assertRaises(CachePayloadTooLarge):
                cache.set(key, {'items': ['x' * 200]}, data_version='v1', now=100)

            self.assertFalse(cache.path_for(key).exists())
