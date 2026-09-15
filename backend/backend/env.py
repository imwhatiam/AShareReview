"""Small, dependency-free reader for the repository root .env file."""

import os
import time
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / '.env'
# 每条配置都重新解析一次 .env 是纯浪费：一个管理命令会问近 200 次配置，在文件
# I/O 昂贵的地方（容器、网络盘、沙箱代理）这些读取会直接主导运行时长。这里按
# 路径缓存解析结果，并最多每 TTL 秒比对一次文件指纹，所以进程长跑期间改 .env
# 仍会生效，只是延迟不超过 TTL。
ENV_CACHE_TTL_SECONDS = 5.0

_PARSE_CACHE: dict[Path, tuple[float, tuple[int, int] | None, dict[str, str]]] = {}


def _fingerprint(path: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)``, or ``None`` when the file is unreadable."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
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


def _file_values() -> dict[str, str]:
    path = ENV_FILE
    now = time.monotonic()
    cached = _PARSE_CACHE.get(path)
    if cached is not None and now - cached[0] < ENV_CACHE_TTL_SECONDS:
        return cached[2]

    fingerprint = _fingerprint(path)
    if fingerprint is not None and cached is not None and cached[1] == fingerprint:
        # 文件没变，只刷新“检查时间”，继续复用已解析的结果。
        _PARSE_CACHE[path] = (now, fingerprint, cached[2])
        return cached[2]

    values = {} if fingerprint is None else _parse(path.read_text(encoding='utf-8'))
    _PARSE_CACHE[path] = (now, fingerprint, values)
    return values


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value
    return _file_values().get(name, default)


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


def get_int_setting(name: str, default: int) -> int:
    """Read a whole-number setting, rejecting anything that is not an integer."""
    value = get_setting(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError as error:
        raise ImproperlyConfigured(
            f'Setting {name} must be an integer, not {value!r}.'
        ) from error


def get_required_int_setting(name: str, *, minimum: int = 0) -> int:
    """Read a required integer setting, rejecting anything below ``minimum``.

    Unlike :func:`get_int_setting` there is no default: a missing or malformed
    value is a configuration error, not a silently substituted fallback. The
    upstream adapters used to carry three byte-identical private copies of this.
    """
    value = get_required_setting(name)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be an integer.') from error
    if parsed < minimum:
        raise ImproperlyConfigured(f'{name} must be at least {minimum}.')
    return parsed


def get_required_float_setting(name: str, *, minimum: float = 0.0) -> float:
    """Read a required float setting, rejecting anything below ``minimum``."""
    value = get_required_setting(name)
    try:
        parsed = float(value)
    except ValueError as error:
        raise ImproperlyConfigured(f'{name} must be numeric.') from error
    if parsed < minimum:
        raise ImproperlyConfigured(f'{name} must be at least {minimum}.')
    return parsed


def get_list_setting(name: str, default: tuple[str, ...] = ()) -> list[str]:
    """Read a comma-separated setting, falling back to ``default`` when unset.

    A missing value **and a blank value** both mean "not configured": ``''``,
    ``'   '`` and ``ENABLED_MODULES=`` all resolve to ``default``. Treating a
    blank value as an explicit empty list is how a single stray ``=`` line
    silently disabled every business module (and could not be caught by the
    unknown-ID validation, which only sees an empty set).
    """
    value = get_setting(name)
    if value is None or not value.strip():
        return list(default)
    return [item.strip() for item in value.split(',') if item.strip()]


def get_path_setting(name: str) -> Path:
    value = get_required_setting(name)
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPOSITORY_ROOT / path
