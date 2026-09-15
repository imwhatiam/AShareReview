"""Shared errors and request headers for the two Kaipanla adapters.

The industry snapshot and the sector fund flow are two endpoints of the same
upstream, and both decode the same JSON envelope. Until 2026-09-15 each adapter
declared its **own** copy of the three exception classes: ``isinstance`` then
failed across the pair, so ``core.api.errors`` could map only the industry
adapter's failures to ``UPSTREAM_*`` and every fund-flow failure logged an empty
``error_code``. There is one set of names, and it lives here.
"""

from backend.env import get_setting


# 两个端点都是同一个 App 的接口，必须报同一个客户端身份。这段 UA 只在
# `.env` 没有配置 `KAIPANLA_USER_AGENT` 时兜底。
DEFAULT_USER_AGENT = 'Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)'


class KaipanlaUnavailableError(RuntimeError):
    """The Kaipanla endpoint rejected or could not complete a request."""


class KaipanlaRateLimitError(KaipanlaUnavailableError):
    """The Kaipanla endpoint refused the request because we are being throttled.

    A subclass on purpose: every existing ``except KaipanlaUnavailableError``
    keeps working, while ``core.api.errors.upstream_error_code`` can single out
    429 as ``UPSTREAM_RATE_LIMITED``.
    """


class KaipanlaPayloadError(RuntimeError):
    """The Kaipanla endpoint returned an unusable response shape."""


def request_headers() -> dict[str, str]:
    """The four request headers both Kaipanla endpoints expect.

    Built here rather than inlined per adapter: the industry adapter used to
    hardcode the ``User-Agent`` while the fund-flow one read
    ``KAIPANLA_USER_AGENT``, so changing that setting silently moved only one of
    the two endpoints.

    A blank ``KAIPANLA_USER_AGENT`` means "not configured" and falls back, in
    line with how the rest of the repository reads blank settings — an empty
    ``User-Agent`` header is never what the operator meant.
    """
    user_agent = (get_setting('KAIPANLA_USER_AGENT') or '').strip() or DEFAULT_USER_AGENT
    return {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'User-Agent': user_agent,
        'Accept-Encoding': 'gzip',
        'Connection': 'Keep-Alive',
    }
