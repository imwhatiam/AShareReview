"""Request-scoped logging: one access line per HTTP request, with a correlation id.

为什么要在 Django 自带的 ``django.server`` / ``django.request`` 之外再加一层：
- 项目真正的读路径会「按需本地生成派生结果」（见各模块 ``services/read_path.py``），
  也就是说一个 GET 可能悄悄花掉几秒。这些既不是 4xx 也不是 5xx，Django 不会记，
  但它们才是这个系统里最值得被看见的请求。
- 一次请求穿过视图、读路径、上游客户端、文件缓存，没有关联 id 就只能靠时间戳猜。
  ``request_id`` 会随响应头 ``X-Request-ID`` 回给调用方，排障时可以直接对齐。

分级策略：客户端错误（4xx）**不**在这里升级为 WARNING —— Django 的
``django.request`` 已经在管状态码的严重级别（5xx 会走它自己的 ``mail_admins``
处理器，真正发不发取决于 ``DJANGO_ADMINS`` 是否配置；见 ``backend/settings.py``
的 Email 段），两边同时升级等于同一个失败被计两次。这里只在「慢」和「异常逃出
中间件」时升级。
"""

import logging
import re
from time import perf_counter
from uuid import uuid4

from django.conf import settings

from core.logging import elapsed_ms, log_event, request_logging_context

logger = logging.getLogger('core.request')

# 外部传入的 request id 会被写进日志，语义上等于日志伪造入口：只接受短的
# ASCII 标识，不合规就丢弃并自己生成一个。
_REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
DEFAULT_SLOW_REQUEST_MS = 1000
# 浏览器与探针的心跳请求：静态资源每次加载都来、健康检查可能每分钟都来，
# 逐条 INFO 记录只会把有信号的请求挤出视野（慢请求仍然会报 WARNING）。
_QUIET_PATH_PREFIXES = ('/static/',)
_QUIET_PATHS = frozenset({'/favicon.ico', '/api/core/health/'})


class RequestLoggingMiddleware:
    """Bind a request id, then log the request once with its duration and user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = self._request_id(request)
        started_at = perf_counter()
        with request_logging_context(
            request_id=request_id,
            method=request.method,
            path=request.path,
        ):
            try:
                response = self.get_response(request)
            except Exception as error:
                # 异常逃出整条中间件链：Django 的日志里只有状态码，这里把方法、
                # 路径、耗时和堆栈一次性记全，然后原样抛出交给上层处理。
                log_event(
                    logger,
                    'http_request_failed',
                    level=logging.ERROR,
                    exc_info=True,
                    method=request.method,
                    path=request.path,
                    duration_ms=elapsed_ms(started_at),
                    error=error,
                )
                raise
            self._log(request, response, started_at)
        # 放在上下文之外赋值：响应头写失败不该影响请求本身。
        response['X-Request-ID'] = request_id
        return response

    def _log(self, request, response, started_at):
        duration_ms = elapsed_ms(started_at)
        path = request.path
        slow = duration_ms >= self._slow_threshold_ms()
        if self._is_quiet(path) and not slow:
            level, event = logging.DEBUG, 'http_request_heartbeat'
        elif slow:
            level, event = logging.WARNING, 'http_request_slow'
        else:
            level, event = logging.INFO, 'http_request'
        log_event(
            logger,
            event,
            level=level,
            method=request.method,
            path=path,
            status=getattr(response, 'status_code', None),
            duration_ms=duration_ms,
            user=self._user_name(request),
        )

    @staticmethod
    def _slow_threshold_ms() -> int:
        return getattr(settings, 'REQUEST_LOG_SLOW_MS', DEFAULT_SLOW_REQUEST_MS)

    @staticmethod
    def _is_quiet(path: str) -> bool:
        return path in _QUIET_PATHS or path.startswith(_QUIET_PATH_PREFIXES)

    @staticmethod
    def _request_id(request) -> str:
        candidate = (request.headers.get('X-Request-ID') or '').strip()
        return candidate if _REQUEST_ID_PATTERN.match(candidate) else uuid4().hex

    @staticmethod
    def _user_name(request) -> str:
        """Return the acting username, resolved *after* authentication ran."""
        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return 'anonymous'
        return user.get_username() or 'anonymous'
