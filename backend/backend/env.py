"""Small, dependency-free reader for the repository root .env file."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / '.env'


def _file_values() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def get_setting(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, _file_values().get(name, default))


def get_required_setting(name: str) -> str:
    value = get_setting(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f'Required setting {name} is not configured.')
    return value


def get_bool_setting(name: str, default: bool = False) -> bool:
    value = get_setting(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    raise ImproperlyConfigured(
        f'Setting {name} must be a boolean value, not {value!r}.'
    )


def get_list_setting(name: str, default: tuple[str, ...] = ()) -> list[str]:
    value = get_setting(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(',') if item.strip()]


def get_path_setting(name: str) -> Path:
    value = get_required_setting(name)
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPOSITORY_ROOT / path
