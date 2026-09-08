from enum import StrEnum

from django.http import JsonResponse

from core.api.responses import api_response


class ErrorCode(StrEnum):
    AUTH_REQUIRED = 'AUTH_REQUIRED'
    INVALID_DATE = 'INVALID_DATE'
    INVALID_PARAMETER = 'INVALID_PARAMETER'
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
