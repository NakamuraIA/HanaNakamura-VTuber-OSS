from __future__ import annotations

import threading

_lock = threading.RLock()
_is_speaking = False


def set_speaking(active: bool) -> None:
    global _is_speaking
    with _lock:
        _is_speaking = bool(active)


def is_speaking(signals=None) -> bool:
    if signals is not None:
        try:
            if bool(getattr(signals, "HANA_SPEAKING", False)):
                return True
        except Exception:
            pass
    with _lock:
        return _is_speaking
