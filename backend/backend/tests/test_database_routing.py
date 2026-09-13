import os
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class EnvironmentTests(SimpleTestCase):
    def test_required_setting_raises_clear_error_when_missing(self):
        from backend import env

        with patch.dict(os.environ, {}, clear=True), patch.object(
            env, 'ENV_FILE', Path('/tmp/missing-a-share-market-review-env')
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                'Required setting DJANGO_SECRET_KEY is not configured.',
            ):
                env.get_required_setting('DJANGO_SECRET_KEY')

    def test_settings_values_are_parsed_from_environment(self):
        from backend.env import get_bool_setting, get_list_setting

        with patch.dict(
            os.environ,
            {
                'DJANGO_DEBUG': 'false',
                'DJANGO_ALLOWED_HOSTS': 'localhost, example.com ,',
            },
            clear=True,
        ):
            self.assertFalse(get_bool_setting('DJANGO_DEBUG'))
            self.assertEqual(
                get_list_setting('DJANGO_ALLOWED_HOSTS'),
                ['localhost', 'example.com'],
            )

class DatabaseRouterTests(SimpleTestCase):
    def setUp(self):
        from backend.db_router import AppDatabaseRouter

        self.router = AppDatabaseRouter()

    def test_routes_each_business_app_to_its_own_database(self):
        model = type('Model', (), {'_meta': type('Meta', (), {'app_label': 'kaipanla'})})

        self.assertEqual(self.router.db_for_read(model), 'kaipanla')
        self.assertEqual(self.router.db_for_write(model), 'kaipanla')

    def test_router_map_is_derived_from_the_module_registry(self):
        """路由映射不是第二份手写清单，逐个模块断言（过去只覆盖 kaipanla）。

        "注册表加了模块、路由忘了加"曾经不会报错：未知 app 静默回退 `default`，
        该模块的数据被写进 core 库。现在映射由注册表推导，这条断言守住它。
        """
        from backend.db_router import BUSINESS_APP_DATABASES
        from core.module_registry import MODULES

        self.assertEqual(
            BUSINESS_APP_DATABASES,
            {module.module_id: module.module_id for module in MODULES},
        )
        for module in MODULES:
            model = type(
                'Model',
                (),
                {'_meta': type('Meta', (), {'app_label': module.module_id})},
            )
            self.assertEqual(self.router.db_for_read(model), module.module_id)
            self.assertEqual(self.router.db_for_write(model), module.module_id)
            self.assertTrue(self.router.allow_migrate(module.module_id, module.module_id))
            self.assertFalse(self.router.allow_migrate('default', module.module_id))

    def test_only_core_and_django_apps_fall_back_to_the_default_database(self):
        from core.module_registry import MODULES

        business_labels = {module.module_id for module in MODULES}
        for app_label in ('core', 'auth', 'contenttypes', 'sessions', 'admin'):
            self.assertNotIn(app_label, business_labels)
            model = type(
                'Model', (), {'_meta': type('Meta', (), {'app_label': app_label})}
            )
            self.assertEqual(self.router.db_for_read(model), 'default')
            self.assertEqual(self.router.db_for_write(model), 'default')

    def test_prevents_cross_database_model_relations(self):
        kaipanla_model = type(
            'KaipanlaModel', (), {'_meta': type('Meta', (), {'app_label': 'kaipanla'})}
        )
        stock_moves_model = type(
            'StockMovesModel', (), {'_meta': type('Meta', (), {'app_label': 'stock_moves'})}
        )

        self.assertFalse(self.router.allow_relation(kaipanla_model(), stock_moves_model()))

    def test_allows_migrations_only_in_the_owning_database(self):
        self.assertTrue(self.router.allow_migrate('kaipanla', 'kaipanla'))
        self.assertFalse(self.router.allow_migrate('default', 'kaipanla'))
        self.assertFalse(self.router.allow_migrate('stock_moves', 'kaipanla'))


class BusinessModuleDatabaseCheckTests(SimpleTestCase):
    def test_current_settings_pass_the_database_check(self):
        from core.checks import check_business_module_databases

        self.assertEqual(check_business_module_databases(app_configs=None), [])

    def test_reports_a_business_module_without_a_database_alias(self):
        from django.conf import settings

        from core.checks import check_business_module_databases

        databases = {
            'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
        }
        with patch.object(settings, 'DATABASES', databases):
            errors = check_business_module_databases(app_configs=None)

        self.assertTrue(errors)
        self.assertEqual({error.id for error in errors}, {'core.E001'})
        self.assertIn('kaipanla', errors[0].msg)
