"""Shared authenticated JSON endpoints for the post-close analysis modules.

``stock_moves``, ``sector_momentum`` and ``hundred_day`` expose the same two
endpoints over their own read path: a ``results`` view that answers with the
day's payload, and a ``dates`` view that lists the days that have one. Both
require a session, both parse an optional ``?date=``, and both answer the same
way when the data cannot be produced yet. Only the user-facing wording — and, for
``hundred_day``, one extra "not enough history" rule — differs, so a module
declares those and gets the handlers back.
"""

from dataclasses import dataclass
from typing import Callable

from django.views.decorators.http import require_GET

from core.api.errors import ApiError, ErrorCode
from core.api.handlers import optional_date, require_authenticated, success


@dataclass(frozen=True)
class UnavailableRule:
    """How one "this day cannot be produced" exception maps to a response.

    A requested date (``?date=`` present) is a 404: the caller asked for a
    specific day and must not be answered with a different one. Without a date
    it is a 202 for the default page entry, which may still be waiting for its
    first run. A ``None`` message falls back to the exception's own text.
    """

    exception: type[BaseException]
    absent_message: str | None = None
    preparing_message: str | None = None
    absent_code: ErrorCode = ErrorCode.DATA_NOT_AVAILABLE
    preparing_code: ErrorCode = ErrorCode.DATA_PREPARING
    preparation_state: str = 'preparing'


def build_read_endpoints(
    *,
    read_result: Callable,
    read_dates: Callable,
    rules: tuple[UnavailableRule, ...],
):
    """Return ``(results, dates)`` Django views bound to a module's read path.

    Modules pass ``read_result``/``read_dates`` as lambdas that look the name up
    on their own module at call time (``lambda date=None: read_hundred_day(date)``)
    rather than as direct references, so ``patch('<module>.views.read_hundred_day')``
    keeps working.
    """
    caught = tuple(rule.exception for rule in rules)

    def _handle(handler, *, requested_date: bool = False):
        try:
            return handler()
        except ApiError as error:
            return error.as_response()
        except caught as error:
            rule = next(item for item in rules if isinstance(error, item.exception))
            message = rule.absent_message if requested_date else rule.preparing_message
            return ApiError(
                rule.absent_code if requested_date else rule.preparing_code,
                message if message is not None else str(error),
                http_status=404 if requested_date else 202,
                preparation_state=rule.preparation_state,
            ).as_response()

    @require_GET
    def results(request):
        requested_date = 'date' in request.GET
        return _handle(lambda: _results(request), requested_date=requested_date)

    def _results(request):
        require_authenticated(request)
        return success(read_result(optional_date(request)))

    @require_GET
    def dates(request):
        return _handle(lambda: _dates(request))

    def _dates(request):
        require_authenticated(request)
        return success(read_dates())

    return results, dates
