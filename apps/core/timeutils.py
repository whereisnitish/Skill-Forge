"""Timezone helpers. Timestamps are stored in UTC; daily planning uses the user's zone."""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time, timedelta

from django.utils import timezone

UTC = zoneinfo.ZoneInfo("UTC")


def get_zone(name: str | None) -> zoneinfo.ZoneInfo:
    if not name:
        return UTC
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return UTC


def user_zone(user) -> zoneinfo.ZoneInfo:
    profile = getattr(user, "profile", None)
    return get_zone(getattr(profile, "timezone", None))


def local_now(user, now: datetime | None = None) -> datetime:
    return (now or timezone.now()).astimezone(user_zone(user))


def local_date(user, now: datetime | None = None) -> date:
    return local_now(user, now).date()


def local_date_for(dt: datetime, zone: zoneinfo.ZoneInfo) -> date:
    return dt.astimezone(zone).date()


def day_bounds(day: date, zone: zoneinfo.ZoneInfo) -> tuple[datetime, datetime]:
    """Return the UTC instants for the start and end of a local calendar day."""
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)
