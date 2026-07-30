"""Всплывающие подсказки для виджетов Tkinter."""

from __future__ import annotations

import contextlib
import tkinter as tk
from typing import Any


class ToolTip:
    """Показывает текст при наведении курсора на виджет."""

    def __init__(self, widget: tk.Misc, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event: Any = None) -> None:
        self._schedule()

    def _on_leave(self, _event: Any = None) -> None:
        self._cancel()
        self._hide()

    def _schedule(self) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        with contextlib.suppress(tk.TclError):
            tip.attributes("-topmost", True)
        label = tk.Label(
            tip,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            foreground="#000000",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=6,
            pady=4,
            wraplength=360,
        )
        label.pack()
        self._tip = tip

    def _hide(self) -> None:
        if self._tip is not None:
            with contextlib.suppress(tk.TclError):
                self._tip.destroy()
            self._tip = None


def tip(widget: tk.Misc, text: str) -> ToolTip:
    """Назначить подсказку виджету и вернуть объект ToolTip."""
    return ToolTip(widget, text)
