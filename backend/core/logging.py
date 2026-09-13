"""Safe structured logging helpers for command runs and HTTP requests.

两个入账口：
- 管理命令：``log_command_event`` / ``log_command_progress`` 用批次上下文把一条
  命令的 start → progress → finish 串起来（字段 module= / dataset= / batch_id=）。
- Web 请求：``log_event`` + 请求上下文（中间件绑定），每条日志都带 ``request_id``；
  该字段由 ``RequestContextFilter`` 兜底注入，所以格式串里可以放心写
  ``%(request_id)s``，第三方库的日志也不会把它写崩。

两条铁律：字段渲染成单行 ``key=value``（可 grep、不可被换行注入），任何值都先过
``redact_sensitive_text``（密钥、Token、Device ID 不落日志）。
"""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone as datetime_timezone
from time import perf_counter

from django.utils import timezone

from backend.env import get_setting


LOGGER_NAME = 'core.management'
PROGRESS_EVENT = 'data_command_progress'
REQUEST_ID_FIELD = 'request_id'
# 单个字段的上限：异常消息可能带整段上游响应，不截断会把一行日志撑成一篇文档。
MAX_FIELD_CHARACTERS = 500
# 进度行只用于回答"命令还在干什么"，所以既要有存在感，又不能淹没终端：
# 默认每 30 秒最多一行，阶段开始/结束各强制一行。
DEFAULT_PROGRESS_INTERVAL_SECONDS = 30.0
_SENSITIVE_SETTINGS = (
    'DJANGO_SECRET_KEY',
    'HITHINK_FINANCE_API_KEY',
    'KPL_DEVICE_ID',
    'KPL_USER_ID',
    'KPL_TOKEN',
)
_NAMED_SECRET_PATTERN = re.compile(
    r'(?i)\b(api[_-]?key|token|device[_-]?id|authorization|password|secret)'
    r'\s*([:=])\s*([^\s,;]+)'
)
_BEARER_TOKEN_PATTERN = re.compile(r'(?i)\bBearer\s+[^\s,;]+')
_WHITESPACE_PATTERN = re.compile(r'\s+')


def redact_sensitive_text(value: object) -> str:
    """Return a safe, concise representation without configured secret values."""
    text = str(value)
    for setting_name in _SENSITIVE_SETTINGS:
        secret = get_setting(setting_name)
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = _NAMED_SECRET_PATTERN.sub(r'\1\2[REDACTED]', text)
    return _BEARER_TOKEN_PATTERN.sub('Bearer [REDACTED]', text)


_command_context: ContextVar[dict | None] = ContextVar('data_command_context', default=None)


class command_logging_context:
    """Bind one running command so nested services log progress with its identity.

    The base command owns the batch identity; services several layers below it
    (industry snapshot collection, fund-flow paging, per-stock price loops) need
    to report progress without threading six arguments through every signature.
    A context variable keeps that plumbing out of the call graph, and keeps the
    progress lines attributable to the same ``batch_id`` as start/finish.
    """

    def __init__(self, *, module_id, dataset_key, business_date, batch_id, dry_run):
        self._context = {
            'module_id': module_id,
            'dataset_key': dataset_key,
            'business_date': business_date,
            'batch_id': batch_id,
            'dry_run': dry_run,
        }
        self._token = None

    def __enter__(self):
        self._token = _command_context.set(self._context)
        return self._context

    def __exit__(self, exc_type, exc_value, traceback):
        if self._token is not None:
            _command_context.reset(self._token)
            self._token = None
        return False


def _format_business_date(value) -> str:
    return value.isoformat() if value else '-'


def _context_prefix(*, module_id, dataset_key, business_date, batch_id, dry_run) -> list[str]:
    return [
        f'module={module_id}',
        f'dataset={dataset_key}',
        f'business_date={_format_business_date(business_date)}',
        f'batch_id={batch_id}',
        f'dry_run={dry_run}',
    ]


def _format_detail(value) -> str:
    """Render one detail as a single token so the event stays greppable."""
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.3f}'
    text = _WHITESPACE_PATTERN.sub('_', redact_sensitive_text(value))
    return text[:MAX_FIELD_CHARACTERS]


_request_context: ContextVar[dict | None] = ContextVar('http_request_context', default=None)


class request_logging_context:
    """Bind the identity of the HTTP request currently being served.

    The middleware owns the lifecycle; anything logged below it (views, read
    paths, upstream clients) inherits the same ``request_id`` without threading
    it through every signature, so one request is greppable end to end.
    """

    def __init__(self, *, request_id, method, path):
        self._context = {
            REQUEST_ID_FIELD: request_id,
            'method': method,
            'path': path,
        }
        self._token = None

    def __enter__(self):
        self._token = _request_context.set(self._context)
        return self._context

    def __exit__(self, exc_type, exc_value, traceback):
        if self._token is not None:
            _request_context.reset(self._token)
            self._token = None
        return False


def current_request_id() -> str | None:
    """Return the request id of the request being served, if any."""
    context = _request_context.get()
    return None if context is None else str(context[REQUEST_ID_FIELD])


class RequestContextFilter(logging.Filter):
    """Guarantee a ``request_id`` attribute on every record a handler renders.

    The plain formatter prints ``%(request_id)s`` for *all* records — including
    Django's own (`django.request`, `django.server`) and third-party ones — so the
    attribute has to exist before formatting. Records emitted inside a request
    inherit the bound id; everything else gets ``-``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, REQUEST_ID_FIELD, None):
            setattr(record, REQUEST_ID_FIELD, current_request_id() or '-')
        return True


# ``extra`` may not overwrite existing LogRecord attributes (logging raises
# KeyError: "Attempt to overwrite 'module' in LogRecord"). Callers are free to
# pass any field name; reserved ones still render in the message, they are just
# not lifted to the top level of the JSON payload.
_RESERVED_RECORD_KEYS = frozenset(
    logging.LogRecord('', 0, '', 0, '', (), None).__dict__
) | {'message', 'asctime'}


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields,
) -> None:
    """Emit one structured event: ``event key=value key=value``.

    Fields are attached via ``extra`` as well, which is how the JSON formatter
    lifts them to top-level keys for log collectors. Values are redacted and
    collapsed to a single line by :func:`_format_detail`.
    """
    message = ' '.join(
        [event, *(f'{key}={_format_detail(value)}' for key, value in fields.items())]
    )
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={
            'event': event,
            'event_fields': {key: value for key, value in fields.items() if key not in _RESERVED_RECORD_KEYS},
        },
    )


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return _format_detail(value)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for collectors (ELK/Loki/CloudWatch).

    Deliberately dependency-free: the project does not ship
    ``python-json-logger``, and a structured payload is a ``json.dumps`` away.
    ``log_event`` fields become top-level keys, so a collector can filter on
    ``event``/``module_id``/``status`` instead of grepping inside ``message``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # 时间戳统一成项目时区（Asia/Shanghai）的本地时间：日志和时间轴上的
            # 业务日期必须能直接对照，不用读者自己 +8。
            'ts': timezone.localtime(
                datetime.fromtimestamp(record.created, tz=datetime_timezone.utc)
            ).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, REQUEST_ID_FIELD, None) or '-',
            'message': record.getMessage(),
        }
        event = getattr(record, 'event', None)
        if event:
            payload['event'] = event
        fields = getattr(record, 'event_fields', None)
        if isinstance(fields, dict):
            payload.update({key: _json_safe(value) for key, value in fields.items()})
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def elapsed_ms(started_at: float) -> float:
    """Milliseconds since a ``perf_counter()`` reading, rounded for log lines."""
    return round((perf_counter() - started_at) * 1000, 1)


def log_command_event(
    level: int,
    event: str,
    *,
    module_id: str,
    dataset_key: str,
    business_date,
    batch_id: str,
    dry_run: bool,
    duration_seconds: float | None = None,
    error: Exception | None = None,
    error_code: str | None = None,
) -> None:
    """Emit one searchable command event without leaking request credentials."""
    fields = [event, *_context_prefix(
        module_id=module_id,
        dataset_key=dataset_key,
        business_date=business_date,
        batch_id=batch_id,
        dry_run=dry_run,
    )]
    if duration_seconds is not None:
        fields.append(f'duration_seconds={duration_seconds:.3f}')
    # 稳定错误码与 HTTP 契约同一套拼写（如 UPSTREAM_RATE_LIMITED），方便按码
    # 直接筛"上游挂了"这类失败；不是上游失败时留空，不误标。
    if error_code is not None:
        fields.append(f'error_code={error_code}')
    if error is not None:
        fields.append(f'error={redact_sensitive_text(error)}')
    logging.getLogger(LOGGER_NAME).log(level, ' '.join(fields))


def log_command_progress(stage: str, *, level: int = logging.INFO, **details) -> bool:
    """Emit a progress event for the running command.

    Returns ``False`` when no command is bound, so services stay silent when they
    are exercised directly (unit tests, API request paths) instead of spraying
    progress lines with no batch to attribute them to.
    """
    context = _command_context.get()
    if context is None:
        return False
    fields = [PROGRESS_EVENT, *_context_prefix(**context), f'stage={stage}']
    fields.extend(f'{key}={_format_detail(value)}' for key, value in details.items())
    logging.getLogger(LOGGER_NAME).log(level, ' '.join(fields))
    return True


class ProgressReporter:
    """Report loop progress often enough to be visible, rarely enough to be quiet.

    Long synchronization loops (thousands of upstream requests) used to be silent
    between the start and finish events, so an operator could not tell a healthy
    run from a hung one. ``advance()`` records one unit of work and emits at most
    one line per interval; ``start()`` and ``report(force=True)`` always emit so
    every phase has a header and a terminal record.
    """

    def __init__(self, stage: str, *, total: int | None = None, min_interval_seconds=None, **details):
        self.stage = stage
        self.total = total
        self.min_interval_seconds = (
            DEFAULT_PROGRESS_INTERVAL_SECONDS
            if min_interval_seconds is None
            else min_interval_seconds
        )
        self.details = details
        self.processed = 0
        self._started_at = perf_counter()
        self._last_emitted_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        return perf_counter() - self._started_at

    def start(self, **details) -> bool:
        """Emit the phase header without consuming the throttle window."""
        payload = dict(self.details)
        payload.update(details)
        return log_command_progress(self.stage, **payload)

    def advance(self, *, count: int = 1, force: bool = False, **details) -> bool:
        self.processed += count
        return self.report(force=force, **details)

    def report(self, *, force: bool = False, **details) -> bool:
        elapsed = self.elapsed_seconds
        if not force and self._last_emitted_at is not None:
            if elapsed - self._last_emitted_at < self.min_interval_seconds:
                return False
        self._last_emitted_at = elapsed
        payload = dict(self.details)
        payload['processed'] = self.processed
        payload['elapsed_seconds'] = round(elapsed, 3)
        if self.total:
            payload['total'] = self.total
            payload['percent'] = round(min(self.processed, self.total) / self.total * 100, 1)
            remaining = self.total - self.processed
            if 0 < self.processed < self.total:
                payload['eta_seconds'] = round(elapsed / self.processed * remaining, 1)
        payload.update(details)
        return log_command_progress(self.stage, **payload)
