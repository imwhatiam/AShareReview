"""Safe presentation helpers for the Django operations center."""

import re


_SENSITIVE_VALUE = re.compile(
    r'(?i)\b(api[_-]?key|token|password|secret|authorization)'
    r'\s*([:=])\s*(?:bearer\s+)?[^\s,;&]+',
)
_QUERY_SECRET = re.compile(
    r'(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&\s]+',
)


def safe_error_summary(value: str) -> str:
    """Redact credential-like values before rendering operational errors."""
    value = _QUERY_SECRET.sub(r'\1[REDACTED]', value)
    return _SENSITIVE_VALUE.sub(r'\1\2 [REDACTED]', value)
