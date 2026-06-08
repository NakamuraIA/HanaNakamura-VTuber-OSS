from __future__ import annotations

import threading
import time

_lock = threading.RLock()
_is_speaking = False
_changed_at = 0.0


def set_speaking(active: bool) -> None:
    global _is_speaking, _changed_at
    with _lock:
        _is_speaking = bool(active)
        _changed_at = time.time()


def is_speaking(signals=None) -> bool:
    if signals is not None:
        try:
            if bool(getattr(signals, "HANA_SPEAKING", False)):
                return True
        except Exception:
            pass
    with _lock:
        return _is_speaking


def changed_at() -> float:
    with _lock:
        return _changed_at
