from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)


def now_local() -> datetime:
    """Current time in Asia/Kolkata (timezone-aware)."""
    return datetime.now(TZ)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_local(s: str) -> datetime:
    """Open-Meteo returns local times like '2026-10-30T14:00' when timezone is set."""
    return datetime.fromisoformat(s).replace(tzinfo=TZ)
