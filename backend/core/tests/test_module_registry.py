import os
from unittest.mock import patch

from django.test import SimpleTestCase


class ModuleRegistryTests(SimpleTestCase):
    def test_returns_enabled_modules_in_navigation_order(self):
        from core.module_registry import get_enabled_modules

        with patch.dict(
            os.environ,
            {'ENABLED_MODULES': 'hundred_day,kaipanla'},
            clear=False,
        ):
            self.assertEqual(
                [module.module_id for module in get_enabled_modules()],
                ['kaipanla', 'hundred_day'],
            )

    def test_module_contract_contains_each_required_public_field(self):
        from core.module_registry import get_enabled_modules

        with patch.dict(os.environ, {'ENABLED_MODULES': 'kaipanla'}, clear=False):
            module = get_enabled_modules()[0]

        self.assertEqual(module.module_id, 'kaipanla')
        self.assertEqual(module.display_name, '开盘啦')
        self.assertEqual(module.frontend_route, '/fund-flow/kaipanla')
        self.assertEqual(module.api_prefix, '/api/kaipanla/')
        self.assertEqual(module.navigation_group, 'fund_flow')
        self.assertTrue(module.requires_login)
