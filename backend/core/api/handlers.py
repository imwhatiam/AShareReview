"""Request-side helpers that every module view needs, defined once.

A module view starts with the same three moves whichever shape it takes — the
three post-close modules that share ``build_read_endpoints`` and the Kaipanla
views that assemble their own handlers both refuse an anonymous caller, read
the optional ``?date=``, and wrap a read result into the shared envelope.
Kaipanla used to carry its own byte-identical copies of all three; they live
here so a change to the envelope or the auth wording only has one place to
land.

The response *shape* helpers (``api_success`` / ``api_response``) stay in
``core.api.responses``; what is here is the request→response glue that would
otherwise be copy-pasted per module.
"""

from core.api.errors import ApiError, ErrorCode
from core.api.responses import api_success
from core.api.validators import parse_iso_date


def require_authenticated(request):
    """Reject an anonymous caller before any read path runs."""
    if not request.user.is_authenticated:
        raise ApiError(ErrorCode.AUTH_REQUIRED, '请先登录。', http_status=401)


def optional_date(request):
    """The day the caller asked for, or ``None`` when it named no date.

    ``None`` is meaningful, not missing input: it asks the read path for its
    own default entry, so the distinction between "no ``date`` key" and
    "``date=``" (invalid, rejected) has to survive here.
    """
    value = request.GET.get('date')
    return None if value is None else parse_iso_date(value)


def success(result):
    """Wrap a module read result into the shared success envelope.

    ``data_updated_at`` is the moment the served rows were written to their
    database — the page shows it as「更新于 HH:MM」. It is deliberately not
    ``generated_at``: the envelope is rebuilt on every request (including cache
    hits), so ``generated_at`` would answer "when did you ask", not "how fresh is
    what you are looking at".
    """
    return api_success(
        data=result.data,
        business_date=result.business_date,
        data_updated_at=result.data_updated_at,
        source=result.source,
        stale=result.stale,
        warnings=list(result.warnings),
    )
