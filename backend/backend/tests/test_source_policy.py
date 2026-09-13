"""Static policy checks for the approved and bounded market-data clients."""

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / 'backend'
APPROVED_REQUEST_CLIENTS = {
    'core/integrations/hithink/client.py',
    'core/integrations/kaipanla/client.py',
    'kaipanla/services/client.py',
}
HITHINK_ENDPOINTS = {
    '/api/meta/tickers/list',
    '/api/a-share/calendar/trading-days',
    '/api/a-share/prices/historical',
    # 全市场实时行情快照：盘中半小时刷新所有个股当日交易数据的通道。
    '/api/a-share/prices/snapshot',
    # 881 行业成分股：用来补齐开盘啦给不出北交所归属的那批股票。
    '/api/a-share-index/catalog/ths-index-list',
    '/api/a-share-index/constituents/ths-stock-list',
}
FORBIDDEN_STOCK_SOURCE_TERMS = (
    'baostock',
    'akshare',
    'tushare',
    'yfinance',
    'selenium',
    'playwright',
    'scrapy',
    'beautifulsoup',
    'bs4',
    'urllib.request',
)


def _imports_requests(source_path: Path) -> bool:
    tree = ast.parse(source_path.read_text(encoding='utf-8'), filename=str(source_path))
    return any(
        isinstance(node, ast.Import) and any(alias.name == 'requests' for alias in node.names)
        or isinstance(node, ast.ImportFrom) and node.module == 'requests'
        for node in ast.walk(tree)
    )


class SourcePolicyTests(SimpleTestCase):
    def test_direct_http_clients_are_limited_to_approved_adapters(self):
        actual = {
            source_path.relative_to(BACKEND_ROOT).as_posix()
            for source_path in BACKEND_ROOT.rglob('*.py')
            if '/tests/' not in source_path.as_posix() and _imports_requests(source_path)
        }
        self.assertEqual(actual, APPROVED_REQUEST_CLIENTS)

    def test_hithink_client_uses_only_approved_stock_and_calendar_endpoints(self):
        source = (BACKEND_ROOT / 'core/integrations/hithink/client.py').read_text(encoding='utf-8')
        for endpoint in HITHINK_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                self.assertIn(f"'{endpoint}'", source)
        requested_paths = set(re.findall(r"self\._get\(\s*'([^']+)'", source))
        self.assertEqual(requested_paths, HITHINK_ENDPOINTS)
        self.assertIn("'X-api-key'", source)
        self.assertIn("get_required_setting('HITHINK_FINANCE_API_KEY')", source)

    def test_business_apps_do_not_bypass_the_controlled_hithink_adapter(self):
        for module_id in ('kaipanla', 'stock_moves', 'sector_momentum', 'hundred_day'):
            for source_path in (BACKEND_ROOT / module_id).rglob('*.py'):
                source = source_path.read_text(encoding='utf-8').lower()
                with self.subTest(module_id=module_id, source_path=source_path):
                    self.assertNotIn('core.integrations.hithink.client', source)
                    self.assertTrue(all(term not in source for term in FORBIDDEN_STOCK_SOURCE_TERMS))

    def test_non_test_code_does_not_include_forbidden_stock_data_clients(self):
        for source_path in BACKEND_ROOT.rglob('*.py'):
            if '/tests/' in source_path.as_posix():
                continue
            source = source_path.read_text(encoding='utf-8').lower()
            with self.subTest(source_path=source_path):
                self.assertTrue(all(term not in source for term in FORBIDDEN_STOCK_SOURCE_TERMS))
