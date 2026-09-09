import json

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from core.api.errors import ApiError, ErrorCode
from core.api.responses import api_success
from core.module_registry import get_enabled_modules


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
        data_version=None,
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
    user = authenticate(request, username=username, password=password)
    if not username or not password or user is None or not user.is_active:
        return ApiError(
            ErrorCode.AUTH_REQUIRED,
            '用户名或密码错误。',
            http_status=401,
        ).as_response()

    django_login(request, user)
    return _session_response(request)


@require_POST
def logout(request):
    django_logout(request)
    return _session_response(request)


@require_GET
def health(request):
    return api_success(
        data={'healthy': True},
        business_date=None,
        data_version=None,
        source='application',
    )


@require_GET
def modules(request):
    return api_success(
        data=[module.as_api_dict() for module in get_enabled_modules()],
        business_date=None,
        data_version=None,
        source='application',
    )


def csrf_failure(request, reason=''):
    return ApiError(
        ErrorCode.INVALID_PARAMETER,
        'CSRF 验证失败。',
        http_status=403,
    ).as_response()
