import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class FileCacheTests(SimpleTestCase):
    def test_hit_requires_matching_identity_and_unexpired_entry(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {'date': '2026-09-08'}, 'v1')
            cache.set(key, {'items': [1]}, cache_identity='v1', now=100)

            self.assertEqual(cache.get(key, cache_identity='v1', now=159), {'items': [1]})
            self.assertIsNone(cache.get(key, cache_identity='v2', now=101))
            self.assertIsNone(cache.get(key, cache_identity='v1', now=160))

    def test_corrupted_cache_is_a_miss(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')
            path = cache.path_for(key)
            path.parent.mkdir(parents=True)
            path.write_text('{not json', encoding='utf-8')

            self.assertIsNone(cache.get(key, cache_identity='v1', now=100))

    def test_a_corrupt_entry_is_reported_with_the_cache_corrupted_code(self):
        """损坏条目仍按未命中处理（会自愈），但必须在日志里与普通未命中区分开。"""
        from core.api.errors import ErrorCode
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')
            path = cache.path_for(key)
            path.parent.mkdir(parents=True)
            path.write_text('{"cache_identity": "v1"}', encoding='utf-8')

            with self.assertLogs('core.services.file_cache', level='WARNING') as captured:
                self.assertIsNone(cache.get(key, cache_identity='v1', now=100))

        # 缺 expires_at / data 的结构损坏同样要报出来。
        message = '\n'.join(captured.output)
        self.assertIn('cache_entry_corrupted', message)
        self.assertIn(f'error_code={ErrorCode.CACHE_CORRUPTED.value}', message)

    def test_a_plain_miss_is_not_reported_as_corruption(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')

            with self.assertNoLogs('core.services.file_cache', level='WARNING'):
                self.assertIsNone(cache.get(key, cache_identity='v1', now=100))

    def test_module_invalidation_does_not_remove_another_modules_files(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=1024)
            own_key = build_cache_key('kaipanla', 'sectors', {}, 'v1')
            other_key = build_cache_key('stock_moves', 'sectors', {}, 'v1')
            cache.set(own_key, {'source': 'kaipanla'}, cache_identity='v1', now=100)
            cache.set(other_key, {'source': 'stock_moves'}, cache_identity='v1', now=100)

            cache.invalidate_module('kaipanla')

            self.assertIsNone(cache.get(own_key, cache_identity='v1', now=101))
            self.assertEqual(
                cache.get(other_key, cache_identity='v1', now=101),
                {'source': 'stock_moves'},
            )

    def test_write_is_atomic_and_rejects_oversized_payload(self):
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import CachePayloadTooLarge, FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=100)
            key = build_cache_key('kaipanla', 'sectors', {}, 'v1')

            with self.assertRaises(CachePayloadTooLarge):
                cache.set(key, {'items': ['x' * 200]}, cache_identity='v1', now=100)

            self.assertFalse(cache.path_for(key).exists())

    def test_cached_payload_is_the_response_json_view(self):
        """缓存存的是响应体的 JSON 视图，Decimal 与 datetime 的写法必须与响应一致。

        往返后类型必然退化（`Decimal` → 字符串、`datetime` → ISO 字符串），这正是
        `DjangoJSONEncoder` 渲染响应体时的行为 —— 缓存命中与未命中在 HTTP 上因此
        完全一致。本用例把这种退化钉住：调用方不得对 `get()` 出来的字段做算术。
        """
        from datetime import datetime, timezone
        from decimal import Decimal

        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        moment = datetime(2026, 9, 13, 4, 30, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=4096)
            key = build_cache_key('stock_moves', 'result', {}, 'v1')
            cache.set(
                key,
                {'change_percent': Decimal('9.990000'), 'finished_at': moment},
                cache_identity='v1',
                now=100,
            )

            stored = json.loads(cache.path_for(key).read_text(encoding='utf-8'))
            self.assertEqual(stored['data']['change_percent'], '9.990000')
            # Django 的编码器把 UTC 的 "+00:00" 规范化成 "Z"。
            self.assertEqual(stored['data']['finished_at'], '2026-09-13T04:30:00Z')
            self.assertEqual(
                cache.get(key, cache_identity='v1', now=101),
                {'change_percent': '9.990000', 'finished_at': '2026-09-13T04:30:00Z'},
            )

    def test_unencodable_payload_raises_instead_of_being_stringified(self):
        """编码不了的对象要显式报错，不能像 `default=str` 那样悄悄写成 "<object at 0x...>"。"""
        from core.services.cache_keys import build_cache_key
        from core.services.file_cache import FileCache

        with TemporaryDirectory() as directory:
            cache = FileCache(Path(directory), ttl_seconds=60, max_bytes=4096)
            key = build_cache_key('stock_moves', 'result', {}, 'v1')

            with self.assertRaises(TypeError):
                cache.set(key, {'payload': object()}, cache_identity='v1', now=100)

            self.assertFalse(cache.path_for(key).exists())
