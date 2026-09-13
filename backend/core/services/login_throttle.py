"""Throttle repeated failed logins for one username from one address.

Why this exists: ``/api/core/login/`` is the only credential endpoint in the
project and it had no failure budget at all — a wrong password cost the caller
nothing but a log line, so a dictionary attack was free.

Scope, stated honestly:

* The counter lives in Django's **cache**, which is the per-process
  ``LocMemCache`` unless ``CACHES`` is configured. That is enough for the
  single-process deployment this project documents; a multi-worker deployment
  should point ``CACHES`` at a shared backend, or the budget is per worker.
* The key is ``(client address, username)``, not either one alone: keying on the
  username lets anyone lock a real user out, keying on the address lets one
  attacker spend the budget of everyone behind a shared proxy.
* The address comes from ``REMOTE_ADDR``, never from ``X-Forwarded-For``: a
  client-supplied header would make the whole thing bypassable by setting one
  header. Behind the documented nginx deployment this collapses all users into
  one bucket, which is a deliberate trade — a false lockout costs a 15-minute
  wait, a bypassed throttle costs the account.
"""

from django.core.cache import cache

from backend.env import get_int_setting

MAX_FAILURES_DEFAULT = 5
WINDOW_SECONDS_DEFAULT = 900


def _policy() -> tuple[int, int]:
    max_failures = get_int_setting('LOGIN_MAX_FAILURES', MAX_FAILURES_DEFAULT)
    window_seconds = get_int_setting('LOGIN_WINDOW_SECONDS', WINDOW_SECONDS_DEFAULT)
    if max_failures < 1 or window_seconds < 1:
        raise ValueError(
            'LOGIN_MAX_FAILURES and LOGIN_WINDOW_SECONDS must both be positive.'
        )
    return max_failures, window_seconds


def _key(username: str, client_address: str) -> str:
    return f'login-failures:{client_address}:{username.strip().lower()}'


def failure_count(username: str, client_address: str) -> int:
    return cache.get(_key(username, client_address), 0) or 0


def is_locked(username: str, client_address: str) -> bool:
    if not username:
        return False
    max_failures, _ = _policy()
    return failure_count(username, client_address) >= max_failures


def record_failure(username: str, client_address: str) -> int:
    """Count one rejection and return the new total for this window."""
    _, window_seconds = _policy()
    key = _key(username, client_address)
    try:
        # 只有第一次写入时设置 TTL：窗口从第一次失败开始算，而不是每次失败都
        # 续期 —— 否则持续尝试会让窗口永远不过期。
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window_seconds)
        return 1


def clear(username: str, client_address: str) -> None:
    cache.delete(_key(username, client_address))
