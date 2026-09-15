import json
from datetime import UTC, date, datetime

from django.test import SimpleTestCase


class ApiContractTests(SimpleTestCase):
    def test_success_response_uses_the_shared_envelope(self):
        from core.api.responses import api_success

        response = api_success(
            data={'items': []},
            business_date=date(2026, 9, 8),
            source='database',
            data_updated_at=datetime(2026, 9, 8, 7, 35, tzinfo=UTC),
        )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['business_date'], '2026-09-08')
        self.assertFalse(body['stale'])
        self.assertEqual(body['source'], 'database')
        self.assertEqual(body['preparation']['state'], 'ready')
        self.assertIsNone(body['error'])
        # 「更新于 HH:MM」读的就是它：**这份数据是什么时候写进库的**，与这次响应是
        # 几点拼出来的（`generated_at`）无关 —— 结果行落库后一直躺在库里，页面随时
        # 打开。时区不影响契约：从 ISO 串要能还原成同一个瞬间。
        self.assertEqual(
            datetime.fromisoformat(body['data_updated_at']),
            datetime(2026, 9, 8, 7, 35, tzinfo=UTC),
        )
        self.assertNotEqual(body['data_updated_at'], body['generated_at'])

    def test_the_envelope_never_fabricates_a_data_time(self):
        """没有数据时刻就如实给 null。

        它会退化成"当前时间"的话，空态与刚取回的数据看起来一样新 —— 这正是这次要
        修掉的东西，所以在这里钉一条。
        """
        from core.api.responses import api_success

        body = json.loads(api_success(
            data=None,
            business_date=None,
            source='cache',
        ).content)

        self.assertIn('data_updated_at', body)
        self.assertIsNone(body['data_updated_at'])

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
