"""Кооперативная отмена длительных операций (Designer / пайплайн)."""

from __future__ import annotations

import threading
from collections.abc import Callable

_cancel = threading.Event()
_on_cancel: Callable[[], None] | None = None


class CancelledError(Exception):
    """Операция прервана пользователем."""


def reset() -> None:
    _cancel.clear()


def request_cancel() -> None:
    _cancel.set()
    cb = _on_cancel
    if cb is not None:
        cb()


def is_cancelled() -> bool:
    return _cancel.is_set()


def check() -> None:
    if _cancel.is_set():
        raise CancelledError("Операция отменена")


def set_kill_callback(cb: Callable[[], None] | None) -> None:
    """Колбэк для принудительного завершения текущего subprocess."""
    global _on_cancel
    _on_cancel = cb
