"""Safe structured logging helpers for data-management commands."""

import logging
import re

from backend.env import get_setting


LOGGER_NAME = 'core.management'
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


def redact_sensitive_text(value: object) -> str:
    """Return a safe, concise representation without configured secret values."""
    text = str(value)
    for setting_name in _SENSITIVE_SETTINGS:
        secret = get_setting(setting_name)
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = _NAMED_SECRET_PATTERN.sub(r'\1\2[REDACTED]', text)
    return _BEARER_TOKEN_PATTERN.sub('Bearer [REDACTED]', text)


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
) -> None:
    """Emit one searchable command event without leaking request credentials."""
    fields = [
        event,
        f'module={module_id}',
        f'dataset={dataset_key}',
        f'business_date={business_date.isoformat() if business_date else "-"}',
        f'batch_id={batch_id}',
        f'dry_run={dry_run}',
    ]
    if duration_seconds is not None:
        fields.append(f'duration_seconds={duration_seconds:.3f}')
    if error is not None:
        fields.append(f'error={redact_sensitive_text(error)}')
    logging.getLogger(LOGGER_NAME).log(level, ' '.join(fields))
