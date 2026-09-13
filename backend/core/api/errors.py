from enum import StrEnum

from django.http import JsonResponse

from core.api.responses import api_response


class ErrorCode(StrEnum):
    AUTH_REQUIRED = 'AUTH_REQUIRED'
    TOO_MANY_ATTEMPTS = 'TOO_MANY_ATTEMPTS'
    INVALID_DATE = 'INVALID_DATE'
    INVALID_PARAMETER = 'INVALID_PARAMETER'
    CSRF_FAILED = 'CSRF_FAILED'
    DATA_NOT_AVAILABLE = 'DATA_NOT_AVAILABLE'
    DATA_PREPARING = 'DATA_PREPARING'
    INSUFFICIENT_HISTORY = 'INSUFFICIENT_HISTORY'
    DATA_INCOMPLETE = 'DATA_INCOMPLETE'
    SYNC_IN_PROGRESS = 'SYNC_IN_PROGRESS'
    UPSTREAM_RATE_LIMITED = 'UPSTREAM_RATE_LIMITED'
    UPSTREAM_UNAVAILABLE = 'UPSTREAM_UNAVAILABLE'
    CACHE_CORRUPTED = 'CACHE_CORRUPTED'
    MODULE_DISABLED = 'MODULE_DISABLED'


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int = 400,
        preparation_state: str = 'unavailable',
        retry_after_seconds: int | None = None,
    ):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.preparation_state = preparation_state
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)

    def as_response(self) -> JsonResponse:
        return api_response(
            status='preparing' if self.http_status == 202 else 'error',
            http_status=self.http_status,
            preparation_state=self.preparation_state,
            retry_after_seconds=self.retry_after_seconds,
            error={'code': self.code.value, 'message': self.message},
        )


def dataset_busy_error(
    message: str = '该数据集正在同步，请稍后重试。',
) -> ApiError:
    """The single 409 answer for "another task already owns this dataset".

    Spec §5.7 maps that situation to ``409 SYNC_IN_PROGRESS`` and §5.8a says a
    contending read serves old data instead. Before this factory, ``kaipanla``
    answered 409 while the three derived modules answered ``202`` (or even
    ``404 DATA_NOT_AVAILABLE`` for an explicit date, which is a lie: the data is
    being written right now). Every module now answers through this one helper,
    so the status code, the code and ``preparation.state`` cannot drift apart.
    """
    return ApiError(
        ErrorCode.SYNC_IN_PROGRESS,
        message,
        http_status=409,
        preparation_state='syncing',
    )


def upstream_error_code(error: BaseException) -> ErrorCode | None:
    """Map an **integration-layer** failure to its stable error code.

    ``UPSTREAM_RATE_LIMITED`` / ``UPSTREAM_UNAVAILABLE`` are declared in the
    response contract, but a read path is not allowed to call an upstream and a
    data command's failure is reported through the command log rather than an
    HTTP body. Mapping here keeps both paths using the same spelling instead of
    each inventing its own, and it is what makes "上游挂了" greppable in
    ``data_command_failed`` / ``upstream_failed`` events.

    Returns ``None`` for anything that is not an upstream-transport failure
    (payload/contract errors, programming errors), so callers can leave the
    field empty instead of mislabelling them.
    """
    from core.integrations.hithink.contracts import (
        HithinkRateLimitError,
        HithinkUnavailableError,
    )
    from core.integrations.kaipanla.client import (
        KaipanlaRateLimitError,
        KaipanlaUnavailableError,
    )

    if isinstance(error, (HithinkRateLimitError, KaipanlaRateLimitError)):
        return ErrorCode.UPSTREAM_RATE_LIMITED
    if isinstance(error, (HithinkUnavailableError, KaipanlaUnavailableError)):
        return ErrorCode.UPSTREAM_UNAVAILABLE
    return None


def upstream_error_code_value(error: BaseException) -> str | None:
    """The string form of :func:`upstream_error_code`, for log fields."""
    code = upstream_error_code(error)
    return code.value if code is not None else None
