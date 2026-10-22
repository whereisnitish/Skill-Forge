"""Fixed-window rate limiting backed by the Django cache.

Production uses Redis, so counters are shared across processes. In local
development the per-process LocMem cache is used, which is adequate for a
single runserver process.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

_PERIODS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

KeyFunc = Callable[[HttpRequest], str | None]


def parse_rate(rate: str) -> tuple[int, int]:
    count, _, unit = rate.partition("/")
    if unit not in _PERIODS or not count.isdigit():
        raise ValueError(f"Invalid rate {rate!r}; expected e.g. '10/m'.")
    return int(count), _PERIODS[unit]


def client_ip(request: HttpRequest) -> str:
    """Return the client IP, honouring X-Forwarded-For only behind trusted proxies."""
    proxies = settings.TRUSTED_PROXY_COUNT
    if proxies > 0:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return request.META.get("REMOTE_ADDR", "unknown")


def _identity(request: HttpRequest, key: str | KeyFunc) -> str | None:
    if callable(key):
        return key(request)
    if key == "ip":
        return client_ip(request)
    if key == "user":
        return str(request.user.pk) if request.user.is_authenticated else None
    if key == "user_or_ip":
        if request.user.is_authenticated:
            return f"u{request.user.pk}"
        return f"ip{client_ip(request)}"
    raise ValueError(f"Unknown rate limit key {key!r}")


def hit(group: str, identity: str, rate: str) -> bool:
    """Record one hit; return True when the caller is over the limit."""
    if not settings.RATELIMIT_ENABLED:
        return False
    limit, period = parse_rate(rate)
    window = int(time.time() // period)
    digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
    cache_key = f"rl:{group}:{digest}:{window}"
    cache.add(cache_key, 0, timeout=period + 5)
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=period + 5)
        count = 1
    return count > limit


def is_limited(request: HttpRequest, group: str, key: str | KeyFunc, rate: str) -> bool:
    identity = _identity(request, key)
    if not identity:
        return False
    return hit(group, identity, rate)


def ratelimit(
    group: str,
    rate: str,
    key: str | KeyFunc = "ip",
    methods: tuple[str, ...] = ("POST",),
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """View decorator. Over-limit requests receive a 429 page or HTMX-friendly response."""

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if request.method in methods and is_limited(request, group, key, rate):
                from .views import rate_limited

                return rate_limited(request)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
