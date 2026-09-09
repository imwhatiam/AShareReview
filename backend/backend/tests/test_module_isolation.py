"""Regression checks for independently deployable business modules."""

import ast
from pathlib import Path

from django.core.management import get_commands
from django.test import SimpleTestCase
from django.urls import resolve

from backend.db_router import AppDatabaseRouter, BUSINESS_APP_DATABASES
from core.module_registry import MODULES


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / 'backend'
BUSINESS_APP_IDS = tuple(BUSINESS_APP_DATABASES)
MODULE_COMMANDS = {
    'kaipanla': 'fetch_kaipanla_sector_fund_flow',
    'eastmoney': 'fetch_eastmoney_sector_fund_flow',
    'stock_moves': 'build_stock_moves',
    'sector_momentum': 'build_sector_momentum',
    'hundred_day': 'build_hundred_day',
}


def _business_imports(source_path: Path) -> set[str]:
    """Return imports that make one business app depend on another."""
    tree = ast.parse(source_path.read_text(encoding='utf-8'), filename=str(source_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split('.')[0])
    return imported


def _relation_targets(source_path: Path) -> set[str]:
    """Return explicit business-app relation targets declared by a model module."""
    tree = ast.parse(source_path.read_text(encoding='utf-8'), filename=str(source_path))
    targets: set[str] = set()
    relation_names = {'ForeignKey', 'ManyToManyField', 'OneToOneField'}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
        if function_name not in relation_names:
            continue
        values = list(node.args)
        values.extend(keyword.value for keyword in node.keywords if keyword.arg == 'to')
        for value in values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                targets.add(value.value.split('.')[0])
    return targets


class ModuleIsolationTests(SimpleTestCase):
    def test_registry_and_database_router_cover_exactly_five_business_apps(self):
        self.assertEqual(tuple(module.module_id for module in MODULES), BUSINESS_APP_IDS)
        self.assertEqual(set(BUSINESS_APP_DATABASES.values()), set(BUSINESS_APP_IDS))

        router = AppDatabaseRouter()
        for module_id in BUSINESS_APP_IDS:
            self.assertTrue(router.allow_migrate(module_id, module_id))
            for other_database in {'default', *BUSINESS_APP_IDS} - {module_id}:
                self.assertFalse(router.allow_migrate(other_database, module_id))

    def test_each_business_app_has_its_own_required_runtime_artifacts(self):
        for module_id in BUSINESS_APP_IDS:
            with self.subTest(module_id=module_id):
                app_root = BACKEND_ROOT / module_id
                self.assertTrue((app_root / 'models.py').is_file())
                self.assertTrue((app_root / 'views.py').is_file())
                self.assertTrue((app_root / 'urls.py').is_file())
                self.assertTrue((app_root / 'services').is_dir())
                self.assertTrue((app_root / 'migrations').is_dir())
                self.assertTrue((app_root / 'tests').is_dir())
                self.assertTrue(
                    (app_root / 'management' / 'commands' / f'{MODULE_COMMANDS[module_id]}.py').is_file()
                )

    def test_business_apps_do_not_import_each_other(self):
        for module_id in BUSINESS_APP_IDS:
            for source_path in (BACKEND_ROOT / module_id).rglob('*.py'):
                with self.subTest(module_id=module_id, source_path=source_path):
                    forbidden = (_business_imports(source_path) & set(BUSINESS_APP_IDS)) - {module_id}
                    self.assertEqual(forbidden, set())

    def test_business_models_do_not_declare_cross_app_relations(self):
        for module_id in BUSINESS_APP_IDS:
            model_path = BACKEND_ROOT / module_id / 'models.py'
            with self.subTest(module_id=module_id):
                forbidden = _relation_targets(model_path) & (set(BUSINESS_APP_IDS) - {module_id})
                self.assertEqual(forbidden, set())

    def test_enabled_modules_expose_their_own_url_and_management_command(self):
        commands = get_commands()
        for module in MODULES:
            with self.subTest(module_id=module.module_id):
                self.assertEqual(commands.get(MODULE_COMMANDS[module.module_id]), module.module_id)
                match = resolve(f'{module.api_prefix}dates/')
                self.assertEqual(match.namespace, module.module_id)

    def test_matrix_script_is_portable_and_covers_every_module(self):
        script_path = PROJECT_ROOT / 'scripts' / 'check_module_matrix.sh'
        self.assertTrue(script_path.is_file())
        script = script_path.read_text(encoding='utf-8')

        self.assertNotIn('/Users/', script)
        self.assertNotIn('/home/', script)
        for module_id, command_name in MODULE_COMMANDS.items():
            self.assertIn(module_id, script)
            self.assertIn(command_name, script)
        self.assertIn('manage.py check', script)
        self.assertIn('migrate --plan', script)
        self.assertIn('manage.py test', script)
