"""In-memory sessions for follow-up questions (no database).

A session holds the data behind the last answer (location, data points with their sources and
fetch times, rule results, forecast series) so follow-up questions can be answered from it
without calling Open-Meteo or SoilGrids again. Sessions expire SESSION_TTL_S after last use,
and at most SESSION_MAX are kept (least recently used dropped first). Restarting the server
clears them all.
"""
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from . import config

_clock = time.monotonic  # replaced in tests


@dataclass
class Session:
    id: str
    context: dict | None = None            # data behind the last answer (see followup.context_from)
    last_used: float = 0.0
    followups: list[float] = field(default_factory=list)  # times of recent follow-ups (rate limit)


_store: "OrderedDict[str, Session]" = OrderedDict()


def _purge() -> None:
    now = _clock()
    for sid in [k for k, s in _store.items() if now - s.last_used > config.SESSION_TTL_S]:
        _store.pop(sid, None)
    while len(_store) > config.SESSION_MAX:
        _store.popitem(last=False)


def get(session_id: str | None) -> Session | None:
    """The live session for this cookie value, or None (unknown or expired)."""
    _purge()
    s = _store.get(session_id or "")
    if s is None:
        return None
    s.last_used = _clock()
    _store.move_to_end(s.id)
    return s


def get_or_create(session_id: str | None) -> Session:
    s = get(session_id)
    if s is None:
        s = Session(id=secrets.token_urlsafe(24), last_used=_clock())  # never trust a client-chosen id
        _store[s.id] = s
        _purge()
    return s


def save_answer(s: Session, context: dict) -> None:
    """A new full answer replaces the stored data. The follow-up allowance is per session, not per answer."""
    s.context = context
    s.last_used = _clock()


def followup_allowance(s: Session) -> tuple[int, float]:
    """(follow-ups used in the window, seconds until the oldest one leaves the window)."""
    now = _clock()
    s.followups = [t for t in s.followups if now - t < config.FOLLOWUP_WINDOW_S]
    wait = (s.followups[0] + config.FOLLOWUP_WINDOW_S - now) if s.followups else 0.0
    return len(s.followups), max(0.0, wait)


def record_followup(s: Session) -> None:
    s.followups.append(_clock())


def clear() -> None:
    _store.clear()
