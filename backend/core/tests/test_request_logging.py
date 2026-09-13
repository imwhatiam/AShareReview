"""Contract tests for request logging and the structured logging helpers.

覆盖三件事：一次请求一定留下一行可定位的访问日志、请求内的所有日志共享同一个
``request_id``、以及任何字段都不会把密钥写出去或把一行日志撑成多行。
"""

import json
import logging
from contextlib import contextmanager
from datetime import date

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.logging import (
    JsonFormatter,
    RequestContextFilter,
    current_request_id,
    log_event,
    request_logging_context,
)
from core.middleware import RequestLoggingMiddleware


class _CapturingHandler(logging.Handler):
    """Collect records so tests can assert on attributes, not just the message."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def capture(logger_name, level=logging.INFO):
    """Attach a handler wired like production (including the request-id filter)."""
    logger = logging.getLogger(logger_name)
    handler = _CapturingHandler()
    handler.addFilter(RequestContextFilter())
    handler.setLevel(level)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _middleware(get_response):
    return RequestLoggingMiddleware(get_response)


class RequestLoggingMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_access_line_records_status_duration_user_and_request_id(self):
        request = self.factory.get('/api/stock-moves/results/')

        with capture('core.request') as handler:
            response = _middleware(lambda _: HttpResponse('{}', status=200))(request)

        self.assertEqual(len(handler.records), 1)
        message = handler.records[0].getMessage()
        self.assertIn('http_request', message)
        self.assertIn('method=GET', message)
        self.assertIn('path=/api/stock-moves/results/', message)
        self.assertIn('status=200', message)
        self.assertIn('duration_ms=', message)
        self.assertIn('user=anonymous', message)
        # 请求 id 同时回给调用方，排障时可以对上号。
        self.assertEqual(
            handler.records[0].request_id,
            response['X-Request-ID'],
        )
        self.assertEqual(len(response['X-Request-ID']), 32)

    def test_inbound_request_id_is_reused_so_callers_can_correlate(self):
        request = self.factory.get('/api/stock-moves/results/', HTTP_X_REQUEST_ID='trace-abc_1')

        with capture('core.request') as handler:
            response = _middleware(lambda _: HttpResponse())(request)

        self.assertEqual(response['X-Request-ID'], 'trace-abc_1')
        self.assertEqual(handler.records[0].request_id, 'trace-abc_1')

    def test_unsafe_inbound_request_id_is_discarded(self):
        # 换行是日志伪造的入口：非法 id 必须被丢掉，而不是原样写进日志。
        request = self.factory.get(
            '/api/stock-moves/results/',
            HTTP_X_REQUEST_ID='bad\ninjected line',
        )

        with capture('core.request') as handler:
            response = _middleware(lambda _: HttpResponse())(request)

        self.assertNotIn('injected', handler.records[0].getMessage())
        self.assertNotEqual(response['X-Request-ID'], 'bad\ninjected line')
        self.assertEqual(len(response['X-Request-ID']), 32)

    def test_every_log_written_inside_the_request_carries_the_same_request_id(self):
        def view(_request):
            log_event(logging.getLogger('core.views.probe'), 'read_generated', business_date=date(2026, 9, 11))
            return HttpResponse()

        request = self.factory.get('/api/stock-moves/results/')

        with (
            capture('core.request') as access,
            capture('core.views.probe') as nested,
        ):
            response = _middleware(view)(request)

        self.assertEqual(access.records[0].request_id, response['X-Request-ID'])
        self.assertEqual(nested.records[0].request_id, response['X-Request-ID'])
        self.assertIsNone(current_request_id())

    @override_settings(REQUEST_LOG_SLOW_MS=0)
    def test_a_slow_request_is_escalated_to_warning(self):
        request = self.factory.get('/api/hundred-day/results/')

        with capture('core.request') as handler:
            _middleware(lambda _: HttpResponse())(request)

        self.assertEqual(handler.records[0].levelno, logging.WARNING)
        self.assertIn('http_request_slow', handler.records[0].getMessage())

    def test_client_errors_stay_at_info_because_django_request_owns_severity(self):
        # 4xx 的严重级别由 django.request 负责（并按配置告警）；这里再升级一次
        # 等于同一个失败被计入两次，所以访问日志保持中性。
        request = self.factory.get('/api/stock-moves/results/')

        with capture('core.request') as handler:
            _middleware(lambda _: HttpResponse(status=404))(request)

        self.assertEqual(handler.records[0].levelno, logging.INFO)
        self.assertIn('status=404', handler.records[0].getMessage())

    def test_health_check_is_quiet_at_info_level(self):
        request = self.factory.get('/api/core/health/')

        with capture('core.request') as handler:
            _middleware(lambda _: HttpResponse())(request)

        self.assertEqual(handler.records, [])
        with capture('core.request', level=logging.DEBUG) as debug_handler:
            _middleware(lambda _: HttpResponse())(request)
        self.assertIn('http_request_heartbeat', debug_handler.records[0].getMessage())

    def test_an_exception_escaping_the_view_is_logged_then_reraised(self):
        def broken(_request):
            raise ValueError('boom')

        request = self.factory.get('/api/stock-moves/results/')

        with capture('core.request') as handler, self.assertRaises(ValueError):
            _middleware(broken)(request)

        self.assertEqual(handler.records[0].levelno, logging.ERROR)
        self.assertIn('http_request_failed', handler.records[0].getMessage())
        # 堆栈只记一次，由这一条带出来。
        self.assertIsNotNone(handler.records[0].exc_info)


class LogEventTests(SimpleTestCase):
    def test_fields_are_single_line_and_secrets_are_redacted(self):
        logger = logging.getLogger('core.probe')

        with capture('core.probe') as handler:
            log_event(logger, 'upstream_failed', note='token=top-secret\nsecond line', status=500)

        self.assertEqual(len(handler.records), 1)
        message = handler.records[0].getMessage()
        self.assertNotIn('top-secret', message)
        self.assertIn('token=[REDACTED]', message)
        self.assertIn('status=500', message)
        self.assertNotIn('\n', message)

    def test_none_and_float_fields_render_like_the_command_log_contract(self):
        logger = logging.getLogger('core.probe')

        with capture('core.probe') as handler:
            log_event(logger, 'read_served', requested_date=None, duration_ms=12.3456)

        message = handler.records[0].getMessage()
        self.assertIn('requested_date=-', message)
        self.assertIn('duration_ms=12.346', message)

    def test_a_reserved_logrecord_name_is_kept_in_the_message(self):
        # ``module`` 是 LogRecord 的保留属性，直接塞进 extra 会抛 KeyError。
        logger = logging.getLogger('core.probe')

        with capture('core.probe') as handler:
            log_event(logger, 'probe', module='clash')

        self.assertIn('module=clash', handler.records[0].getMessage())

    def test_long_values_are_truncated(self):
        logger = logging.getLogger('core.probe')

        with capture('core.probe') as handler:
            log_event(logger, 'probe', detail='x' * 2000)

        self.assertLess(len(handler.records[0].getMessage()), 700)


class JsonFormatterTests(SimpleTestCase):
    def test_fields_become_top_level_keys_on_one_line(self):
        logger = logging.getLogger('core.probe')
        formatter = JsonFormatter()

        record = logger.makeRecord(
            'core.probe',
            logging.INFO,
            __file__,
            1,
            'read_generated module_id=stock_moves duration_ms=12.500',
            (),
            None,
            extra={'event': 'read_generated', 'event_fields': {'module_id': 'stock_moves', 'duration_ms': 12.5}},
        )
        record.request_id = 'trace-1'

        payload = json.loads(formatter.format(record))

        self.assertEqual(payload['event'], 'read_generated')
        self.assertEqual(payload['module_id'], 'stock_moves')
        self.assertEqual(payload['duration_ms'], 12.5)
        self.assertEqual(payload['request_id'], 'trace-1')
        self.assertEqual(payload['level'], 'INFO')
        # 项目时区（Asia/Shanghai）的本地时间，和业务日期能直接对照。
        self.assertTrue(payload['ts'].endswith('+08:00'))

    def test_records_without_event_fields_still_render(self):
        # Django 自己的日志（django.request 等）没有 event/event_fields 属性，
        # 格式化器必须照样工作。
        logger = logging.getLogger('django.request')
        formatter = JsonFormatter()
        record = logger.makeRecord(
            'django.request', logging.ERROR, __file__, 1, 'Internal Server Error: /x', (), None
        )

        payload = json.loads(formatter.format(record))

        self.assertEqual(payload['message'], 'Internal Server Error: /x')
        self.assertEqual(payload['request_id'], '-')


class AuthenticationLoggingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_failed_login_is_logged_at_warning_without_the_password(self):
        with capture('core.auth') as handler:
            response = self.client.post(
                '/api/core/login/',
                data=json.dumps({'username': 'nobody', 'password': 'hunter2'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 401)
        message = handler.records[0].getMessage()
        self.assertEqual(handler.records[0].levelno, logging.WARNING)
        self.assertIn('login_rejected', message)
        self.assertIn('username=nobody', message)
        self.assertNotIn('hunter2', message)

    def test_successful_login_and_logout_are_logged_with_the_user(self):
        get_user_model().objects.create_user(username='reviewer', password='s3cret-pass')

        with capture('core.auth') as handler:
            login_response = self.client.post(
                '/api/core/login/',
                data=json.dumps({'username': 'reviewer', 'password': 's3cret-pass'}),
                content_type='application/json',
            )
            logout_response = self.client.post('/api/core/logout/')

        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(logout_response.status_code, 200)
        messages = [record.getMessage() for record in handler.records]
        self.assertTrue(any('login_succeeded' in message for message in messages))
        self.assertTrue(any('logout' in message for message in messages))
        self.assertNotIn('s3cret-pass', '\n'.join(messages))


class RequestLoggingContextTests(SimpleTestCase):
    def test_context_is_cleared_after_the_request(self):
        with request_logging_context(request_id='abc', method='GET', path='/x'):
            self.assertEqual(current_request_id(), 'abc')

        self.assertIsNone(current_request_id())
