import json
from datetime import date

from django.test import SimpleTestCase


class ApiContractTests(SimpleTestCase):
    def test_success_response_uses_the_shared_envelope(self):
        from core.api.responses import api_success

        response = api_success(
            data={'items': []},
            business_date=date(2026, 9, 8),
            data_version='prices-20260908-v1',
            source='database',
        )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['business_date'], '2026-09-08')
        self.assertEqual(body['data_version'], 'prices-20260908-v1')
        self.assertFalse(body['stale'])
        self.assertEqual(body['source'], 'database')
        self.assertEqual(body['preparation']['state'], 'ready')
        self.assertIsNone(body['error'])

    def test_preparing_error_has_stable_code_and_202_status(self):
        from core.api.errors import ApiError, ErrorCode

        response = ApiError(
            ErrorCode.DATA_PREPARING,
            '数据正在准备中。',
            http_status=202,
            preparation_state='preparing',
            retry_after_seconds=30,
        ).as_response()

        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'preparing')
        self.assertEqual(body['error']['code'], 'DATA_PREPARING')
        self.assertEqual(body['preparation']['retry_after_seconds'], 30)

    def test_date_and_numeric_validators_reject_invalid_values(self):
        from core.api.errors import ApiError
        from core.api.validators import parse_iso_date, parse_rank_count, parse_window_days

        self.assertEqual(parse_iso_date('2026-09-08'), date(2026, 9, 8))
        self.assertEqual(parse_window_days('5'), 5)
        self.assertEqual(parse_rank_count('30', 'inflow_top'), 30)
        for value in ('20260908', '<script>', '2026-99-99'):
            with self.assertRaises(ApiError) as context:
                parse_iso_date(value)
            self.assertEqual(context.exception.code, 'INVALID_DATE')
        for value in ('0', '21', '999999999999999999999'):
            with self.assertRaises(ApiError) as context:
                parse_window_days(value)
            self.assertEqual(context.exception.code, 'INVALID_PARAMETER')
        with self.assertRaises(ApiError):
            parse_rank_count('31', 'inflow_top')
