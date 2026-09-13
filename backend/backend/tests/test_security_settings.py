"""Production configuration safety checks that do not need a running server."""

import os
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from backend.env import (
    get_bool_setting,
    get_int_setting,
    get_list_setting,
    get_required_setting,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SecuritySettingsTests(SimpleTestCase):
    def test_runtime_security_settings_are_safe_by_default(self):
        # 必须读 .env 的原始值：测试运行器会先把 settings.DEBUG 强制成 False，
        # 用 settings.DEBUG 判断会永远认为"这是生产口径"。只有这一条用例依赖部署
        # 配置，其余用例与 .env 无关，不能一起跳过。
        if get_bool_setting('DJANGO_DEBUG', default=False):
            self.skipTest(
                '本机 .env 是调试口径（DJANGO_DEBUG=true），该用例只对生产口径的 .env '
                '有意义；按 .env.example 换成生产配置后会自动生效。'
            )

        self.assertFalse(settings.DEBUG)
        self.assertTrue(settings.ALLOWED_HOSTS)
        # 这里**不能**写 `assertEqual(settings.SECRET_KEY, get_required_setting(...))`：
        # settings.py 就是那么赋值的，两边同源、恒真，只会给出一条假的安全感。
        # 要守的是"它不是模板占位符、也不短"—— 能真正挡住"照抄 .env.example 上线"。
        self.assertGreaterEqual(len(settings.SECRET_KEY), 32)
        self.assertNotIn('replace-with', settings.SECRET_KEY)
        self.assertNotIn('django-insecure', settings.SECRET_KEY)
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.TIME_ZONE, 'Asia/Shanghai')

    def test_env_helpers_reject_malformed_values_instead_of_falling_back(self):
        """畸形配置必须当场报错，不能悄悄退回默认值。

        这是"配置写错了不会静默失效"的守门用例：`DJANGO_DEBUG=treu` 若退回默认值，
        生产环境会带着"以为打开了调试"的配置继续跑；而列表值退化成空列表，曾经就
        是把全部业务模块一次性关掉的那条路（见 `get_list_setting` 的说明）。

        用例通过 `os.environ` 注入，不去碰仓库根的 `.env`。
        """
        with patch.dict(os.environ, {'CONTRACT_BOOL': 'treu'}):
            with self.assertRaises(ImproperlyConfigured):
                get_bool_setting('CONTRACT_BOOL', default=False)
        with patch.dict(os.environ, {'CONTRACT_BOOL': ''}):
            self.assertTrue(get_bool_setting('CONTRACT_BOOL', default=True))

        with patch.dict(os.environ, {'CONTRACT_INT': '12x'}):
            with self.assertRaises(ImproperlyConfigured):
                get_int_setting('CONTRACT_INT', 1)

        with patch.dict(os.environ, {'CONTRACT_REQUIRED': '   '}):
            with self.assertRaises(ImproperlyConfigured):
                get_required_setting('CONTRACT_REQUIRED')

        # 空白值 = "没配置"（等价于缺省），不是"显式的空列表"。
        with patch.dict(os.environ, {'CONTRACT_LIST': '  '}):
            self.assertEqual(get_list_setting('CONTRACT_LIST', ('kaipanla',)), ['kaipanla'])
        with patch.dict(os.environ, {'CONTRACT_LIST': 'a, ,b'}):
            self.assertEqual(get_list_setting('CONTRACT_LIST'), ['a', 'b'])

    def test_settings_read_sensitive_and_environment_specific_values_via_env_helpers(self):
        source = (PROJECT_ROOT / 'backend' / 'backend' / 'settings.py').read_text(encoding='utf-8')
        self.assertIn("get_required_setting('DJANGO_SECRET_KEY')", source)
        self.assertIn("get_bool_setting('DJANGO_DEBUG', default=False)", source)
        self.assertIn("get_list_setting('DJANGO_ALLOWED_HOSTS')", source)
        self.assertNotIn('/Users/', source)
        self.assertNotIn('/home/', source)

    def test_gitignore_excludes_runtime_secrets_and_generated_data(self):
        ignored = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8')
        for pattern in (
            '.env',
            '*.sqlite3',
            'backend/data/',
            'backend/cache/',
            'frontend/node_modules/',
            'frontend/dist/',
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignored)

    def test_example_environment_uses_non_secret_placeholders(self):
        example = (PROJECT_ROOT / '.env.example').read_text(encoding='utf-8')
        self.assertIn('DJANGO_SECRET_KEY=replace-with-a-long-random-secret', example)
        self.assertIn('HITHINK_FINANCE_API_KEY=replace-with-api-key', example)
        self.assertIn('KPL_DEVICE_ID=\n', example)
        self.assertIn('KPL_USER_ID=\n', example)
        self.assertIn('KPL_TOKEN=\n', example)
        self.assertIn('KAIPANLA_INDUSTRY_API_URL=https://apphis.longhuvip.com/w1/api/index.php', example)
        self.assertIn('DJANGO_DEBUG=false', example)
