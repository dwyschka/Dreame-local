"""Kleiner Ringpuffer fuer Diagnose-Ereignisse (Web-UI/API)."""
from __future__ import annotations

import time
from collections import deque
from typing import Any

_EVENTS: deque[dict[str, Any]] = deque(maxlen=300)


def add(kind: str, **data: Any) -> None:
    entry = {"ts": time.strftime("%H:%M:%S"), "kind": kind, **data}
    _EVENTS.append(entry)


def all() -> list[dict[str, Any]]:
    return list(reversed(_EVENTS))


def clear() -> None:
    _EVENTS.clear()
