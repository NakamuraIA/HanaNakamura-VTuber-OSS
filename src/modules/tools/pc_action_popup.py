from __future__ import annotations

import time
import tkinter as tk

try:
    import winsound
except ImportError:  # pragma: no cover - Windows-first fallback
    winsound = None


COLORS = {
    "bg_darkest": "#08080a",
    "bg_card": "#16161f",
    "border": "#36384c",
    "border_strong": "#50536f",
    "green": "#4ade80",
    "yellow": "#facc15",
    "purple_dim": "#be4b8b",
    "purple_neon": "#f472b6",
    "text_primary": "#e2e8f0",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
}

FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_BODY = ("Segoe UI", 13)
FONT_SMALL = ("Segoe UI", 11)


def _pit_pit() -> None:
    if winsound is None:
        return
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass


def confirm_pc_action_popup(
    *,
    title: str,
    body: str,
    risk_label: str,
    timeout_seconds: int = 15,
    parent=None,
) -> bool:
    """Show a small topmost Windows confirmation popup for risky PC actions."""

    _pit_pit()
    temp_root = None
    if parent is None:
        temp_root = tk.Tk()
        temp_root.withdraw()
        parent = temp_root

    result = {"value": False}
    started_at = time.time()
    state = {"closed": False, "after_ids": []}

    popup = tk.Toplevel(parent)
    popup.attributes("-topmost", True)
    popup.resizable(False, False)
    popup.title(title)
    popup.configure(bg=COLORS["bg_darkest"], bd=0, highlightthickness=0)
    popup.withdraw()
    try:
        popup.transient(parent)
    except Exception:
        pass

    width = 360
    height = 210
    popup.update_idletasks()
    screen_w = popup.winfo_screenwidth()
    x_pos = max(20, screen_w - width - 28)
    y_pos = 42
    popup.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    shell = tk.Frame(
        popup,
        bg=COLORS["bg_card"],
        bd=0,
        highlightthickness=2,
        highlightbackground=COLORS["border_strong"],
        highlightcolor=COLORS["border_strong"],
        padx=16,
        pady=14,
    )
    shell.pack(fill="both", expand=True)

    tk.Label(
        shell,
        text=title,
        font=FONT_TITLE,
        fg=COLORS["text_primary"],
        bg=COLORS["bg_card"],
        anchor="w",
        justify="left",
    ).pack(fill="x")

    tk.Label(
        shell,
        text=f"Risco: {risk_label}",
        font=FONT_SMALL,
        fg=COLORS["yellow"] if risk_label != "baixo" else COLORS["green"],
        bg=COLORS["bg_card"],
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    tk.Label(
        shell,
        text=body,
        font=FONT_BODY,
        fg=COLORS["text_secondary"],
        bg=COLORS["bg_card"],
        wraplength=width - 46,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(10, 10))

    countdown_label = tk.Label(
        shell,
        text=f"Negando automaticamente em {timeout_seconds}s",
        font=FONT_SMALL,
        fg=COLORS["text_muted"],
        bg=COLORS["bg_card"],
        anchor="w",
        justify="left",
    )
    countdown_label.pack(fill="x", pady=(0, 10))

    actions = tk.Frame(shell, bg=COLORS["bg_card"], bd=0, highlightthickness=0)
    actions.pack(fill="x")

    def _cancel_after_callbacks() -> None:
        while state["after_ids"]:
            after_id = state["after_ids"].pop()
            try:
                popup.after_cancel(after_id)
            except Exception:
                pass

    def _safe_after(delay_ms: int, callback):
        if state["closed"]:
            return None

        def _wrapped():
            if state["closed"] or not popup.winfo_exists():
                return
            callback()

        after_id = popup.after(delay_ms, _wrapped)
        state["after_ids"].append(after_id)
        return after_id

    def _finish(value: bool) -> None:
        if state["closed"]:
            return
        state["closed"] = True
        result["value"] = bool(value)
        _cancel_after_callbacks()
        try:
            popup.grab_release()
        except Exception:
            pass
        try:
            popup.withdraw()
        except Exception:
            pass
        try:
            popup.destroy()
        except Exception:
            pass

    tk.Button(
        actions,
        text="Negar",
        width=12,
        height=1,
        font=FONT_SMALL,
        fg=COLORS["text_primary"],
        bg=COLORS["bg_darkest"],
        activeforeground=COLORS["text_primary"],
        activebackground="#442323",
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        command=lambda: _finish(False),
        cursor="hand2",
    ).pack(side="left")

    tk.Button(
        actions,
        text="Permitir",
        width=12,
        height=1,
        font=FONT_SMALL,
        fg=COLORS["text_primary"],
        bg=COLORS["purple_dim"],
        activeforeground=COLORS["text_primary"],
        activebackground=COLORS["purple_neon"],
        relief="flat",
        bd=0,
        command=lambda: _finish(True),
        cursor="hand2",
    ).pack(side="right")

    def _tick() -> None:
        elapsed = int(time.time() - started_at)
        remaining = max(0, timeout_seconds - elapsed)
        countdown_label.configure(text=f"Negando automaticamente em {remaining}s")
        if remaining <= 0:
            _finish(False)
            return
        _safe_after(250, _tick)

    popup.bind("<Escape>", lambda _event=None: _finish(False))
    popup.bind("<Return>", lambda _event=None: _finish(True))
    popup.bind("<KP_Enter>", lambda _event=None: _finish(True))
    for key in ("s", "S", "y", "Y"):
        popup.bind(key, lambda _event=None: _finish(True))
    for key in ("n", "N"):
        popup.bind(key, lambda _event=None: _finish(False))
    popup.protocol("WM_DELETE_WINDOW", lambda: _finish(False))

    try:
        popup.grab_set()
    except Exception:
        pass

    popup.deiconify()
    popup.update_idletasks()
    popup.lift()
    popup.attributes("-topmost", True)
    try:
        popup.focus_force()
    except Exception:
        pass

    _safe_after(0, popup.focus_force)
    _safe_after(0, popup.lift)
    _safe_after(250, _tick)
    popup.wait_window()

    if temp_root is not None:
        try:
            temp_root.destroy()
        except Exception:
            pass

    return result["value"]
