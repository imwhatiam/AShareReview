import json
import logging

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from core.api.errors import ApiError, ErrorCode
from core.api.responses import api_success
from core.logging import log_event
from core.module_registry import get_enabled_modules
from core.services import login_throttle
from core.services.calendar import calendar_coverage

# 独立的 core.auth 名字：鉴权事件是安全审计要单独筛的一类，混在 core.views 里
# 就得靠消息文本区分。只记录「谁在什么时候失败了」，绝不记录密码或凭据原文。
auth_logger = logging.getLogger('core.auth')

logger = logging.getLogger(__name__)


def _user_summary(user):
    if not user.is_authenticated:
        return None
    return {
        'id': user.pk,
        'username': user.get_username(),
        'is_staff': user.is_staff,
    }


def _session_data(request):
    return {
        'authenticated': request.user.is_authenticated,
        'user': _user_summary(request.user),
        'csrf_token': get_token(request),
    }


def _session_response(request):
    return api_success(
        data=_session_data(request),
        business_date=None,
        source='application',
    )


def _credentials(request):
    try:
        payload = json.loads(request.body)
    except (TypeError, json.JSONDecodeError):
        return None, None

    if not isinstance(payload, dict):
        return None, None
    username = payload.get('username')
    password = payload.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        return None, None
    return username, password


@require_GET
def session(request):
    return _session_response(request)


@require_POST
def login(request):
    username, password = _credentials(request)
    client_address = request.META.get('REMOTE_ADDR') or 'unknown'
    # 先看失败预算再看密码：锁定期间连密码比对都不做，也不区分「用户名不存在 /
    # 密码错误 / 账号停用」，日志粒度与响应一致。
    if login_throttle.is_locked(username, client_address):
        log_event(
            auth_logger,
            'login_throttled',
            level=logging.WARNING,
            username=username,
        )
        return ApiError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            '登录失败次数过多，请稍后再试。',
            http_status=429,
        ).as_response()

    user = authenticate(request, username=username, password=password)
    if not username or not password or user is None or not user.is_active:
        # 失败原因不区分「用户不存在 / 密码错误 / 账号停用」：日志里也保持同样
        # 的粒度，避免把用户名枚举的结果顺手写进日志。
        failures = (
            login_throttle.record_failure(username, client_address) if username else 0
        )
        log_event(
            auth_logger,
            'login_rejected',
            level=logging.WARNING,
            username=username,
            failures=failures,
        )
        return ApiError(
            ErrorCode.AUTH_REQUIRED,
            '用户名或密码错误。',
            http_status=401,
        ).as_response()

    login_throttle.clear(username, client_address)
    django_login(request, user)
    log_event(auth_logger, 'login_succeeded', user_id=user.pk, username=user.get_username())
    return _session_response(request)


@require_POST
def logout(request):
    user = request.user
    # 先把身份读出来再登出：django_logout 会把 request.user 换成 AnonymousUser。
    actor = (
        {'user_id': user.pk, 'username': user.get_username()}
        if getattr(user, 'is_authenticated', False)
        else None
    )
    django_logout(request)
    if actor is not None:
        log_event(auth_logger, 'logout', **actor)
    return _session_response(request)


@require_GET
def health(request):
    # 存活检查本身不碰上游，但交易日口径的"依赖还剩多少覆盖"必须在这里可见：
    # chinese-calendar 的假期表按年内置，未覆盖年份会静默退化成"工作日即交易日"，
    # 而唯一的安全兜底（上游日历）已经删除。等到第一次请求被上游拒绝才发现就太晚了。
    return api_success(
        data={
            'healthy': True,
            'trading_calendar': calendar_coverage(),
        },
        business_date=None,
        source='application',
    )


@require_GET
def modules(request):
    return api_success(
        data=[module.as_api_dict() for module in get_enabled_modules()],
        business_date=None,
        source='application',
    )


def csrf_failure(request, reason=''):
    """Answer a CSRF rejection with its own error code, not ``INVALID_PARAMETER``.

    The HTTP status was always right (403), but the code was not: it told the
    client "one of your parameters is wrong", which is indistinguishable from a
    genuine bad-request and sends the user hunting for a bug in the form instead of
    reloading an expired page. ``CSRF_FAILED`` is a state the caller can act on
    (re-fetch the token / re-login), so it gets its own code.

    Django calls this view for both a missing/expired token and a failed
    ``Origin``/``Referer`` check, so the reason is logged — that is the difference
    between "会话过期" and "反代把 Origin 改掉了".
    """
    log_event(
        auth_logger,
        'csrf_rejected',
        level=logging.WARNING,
        reason=reason,
        path=request.path,
        error_code=ErrorCode.CSRF_FAILED.value,
    )
    return ApiError(
        ErrorCode.CSRF_FAILED,
        'CSRF 验证失败，请刷新页面后重试。',
        http_status=403,
    ).as_response()


def module_disabled_view(module):
    """Answer every request under a disabled module's prefix with JSON.

    A disabled module used to fall through to Django's HTML 404, so a caller
    could not tell "this module is switched off" (a stable, declared
    ``MODULE_DISABLED``) from "this URL does not exist", and the response broke
    the "every /api/ answer is a JSON envelope" contract.
    """

    def disabled(request):
        log_event(
            logger,
            'module_disabled',
            module_id=module.module_id,
            path=request.path,
            error_code=ErrorCode.MODULE_DISABLED.value,
        )
        return ApiError(
            ErrorCode.MODULE_DISABLED,
            f'模块「{module.display_name}」当前未启用。',
            http_status=404,
        ).as_response()

    disabled.__name__ = f'disabled_{module.module_id}'
    return disabled
