"""Production configuration safety checks that do not need a running server."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from backend.env import get_required_setting


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SecuritySettingsTests(SimpleTestCase):
    def test_runtime_security_settings_are_safe_by_default(self):
        self.assertFalse(settings.DEBUG)
        self.assertTrue(settings.ALLOWED_HOSTS)
        self.assertEqual(settings.SECRET_KEY, get_required_setting('DJANGO_SECRET_KEY'))
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.TIME_ZONE, 'Asia/Shanghai')

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
