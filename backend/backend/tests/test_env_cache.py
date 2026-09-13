import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


class EnvironmentCacheTests(SimpleTestCase):
    """`.env` 若每次取配置都重读一遍，一条管理命令会产生近 200 次文件读取。"""

    def _write_env(self, directory: str, text: str) -> Path:
        path = Path(directory) / '.env'
        path.write_text(text, encoding='utf-8')
        return path

    def test_repeated_setting_lookups_parse_the_env_file_once(self):
        from backend import env

        with TemporaryDirectory() as directory:
            path = self._write_env(directory, 'SOME_SETTING=first\n')
            with (
                patch.object(env, 'ENV_FILE', path),
                patch.dict(os.environ, {}, clear=True),
                patch.object(env, '_parse', wraps=env._parse) as parse,
                patch.object(env, 'ENV_CACHE_TTL_SECONDS', 300),
            ):
                self.assertEqual(env.get_setting('SOME_SETTING'), 'first')
                self.assertEqual(env.get_setting('SOME_SETTING'), 'first')
                self.assertIsNone(env.get_setting('OTHER_SETTING'))
                self.assertFalse(env.get_bool_setting('SOME_BOOL'))

        self.assertEqual(parse.call_count, 1)

    def test_changed_env_file_is_reparsed_after_the_cache_ttl(self):
        from backend import env

        with TemporaryDirectory() as directory:
            self._write_env(directory, 'SOME_SETTING=first\n')
            with (
                patch.object(env, 'ENV_FILE', Path(directory) / '.env'),
                patch.dict(os.environ, {}, clear=True),
                patch.object(env, 'ENV_CACHE_TTL_SECONDS', 0),
            ):
                self.assertEqual(env.get_setting('SOME_SETTING'), 'first')

                self._write_env(directory, 'SOME_SETTING=changed-value\n')

                self.assertEqual(env.get_setting('SOME_SETTING'), 'changed-value')

    def test_missing_env_file_provides_no_file_values(self):
        from backend import env

        with (
            patch.object(env, 'ENV_FILE', Path('/tmp/missing-a-share-env-cache-test')),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertIsNone(env.get_setting('DJANGO_SECRET_KEY'))

    def test_environment_variables_still_win_over_the_file_cache(self):
        from backend import env

        with patch.dict(os.environ, {'SOME_SETTING': 'from-environment'}, clear=True):
            with patch.object(env, '_parse', wraps=env._parse) as parse:
                self.assertEqual(env.get_setting('SOME_SETTING'), 'from-environment')

        # 环境变量命中时不该再去读文件。
        self.assertEqual(parse.call_count, 0)


class ListSettingTests(SimpleTestCase):
    """`get_list_setting` 必须与 `get_bool_setting` / `get_int_setting` 同语义：
    空值等于"没配置"，回退默认值，而不是"显式要求空列表"。"""

    def test_blank_values_fall_back_to_the_default(self):
        from backend import env

        for blank in ('', '   ', '\t'):
            with self.subTest(value=repr(blank)):
                with patch.dict(os.environ, {'ENABLED_MODULES': blank}, clear=False):
                    self.assertEqual(
                        env.get_list_setting('ENABLED_MODULES', ('kaipanla', 'hundred_day')),
                        ['kaipanla', 'hundred_day'],
                    )

    def test_env_file_blank_value_also_falls_back_to_the_default(self):
        from backend import env

        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('ENABLED_MODULES=\n', encoding='utf-8')
            with (
                patch.object(env, 'ENV_FILE', path),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    env.get_list_setting('ENABLED_MODULES', ('kaipanla',)),
                    ['kaipanla'],
                )

    def test_missing_setting_falls_back_to_the_default(self):
        from backend import env

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env.get_list_setting('NOT_DEFINED_ANYWHERE', ('a',)), ['a'])
            self.assertEqual(env.get_list_setting('NOT_DEFINED_ANYWHERE'), [])

    def test_values_are_split_on_commas_and_trimmed(self):
        from backend import env

        with patch.dict(os.environ, {'SOME_LIST': ' a , b ,, c '}, clear=False):
            self.assertEqual(env.get_list_setting('SOME_LIST'), ['a', 'b', 'c'])
