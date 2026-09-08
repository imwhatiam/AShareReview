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

    def test_prevents_cross_database_model_relations(self):
        kaipanla_model = type(
            'KaipanlaModel', (), {'_meta': type('Meta', (), {'app_label': 'kaipanla'})}
        )
        eastmoney_model = type(
            'EastmoneyModel', (), {'_meta': type('Meta', (), {'app_label': 'eastmoney'})}
        )

        self.assertFalse(self.router.allow_relation(kaipanla_model(), eastmoney_model()))

    def test_allows_migrations_only_in_the_owning_database(self):
        self.assertTrue(self.router.allow_migrate('kaipanla', 'kaipanla'))
        self.assertFalse(self.router.allow_migrate('default', 'kaipanla'))
        self.assertFalse(self.router.allow_migrate('eastmoney', 'kaipanla'))
