"""
Game Time — tiny desktop converter
==================================
Type an absolute game time in seconds; see it as period-relative 'Pn m.ss'.

    2603.003  ->  P3 3.23

Formatting mirrors _period_time_str in hockey/visualize/game_canvas.py so the
labels here match the ones on the charts.

Run:
    python game_time.py
"""
from __future__ import annotations

import tkinter as tk

PERIOD_LENGTH = 1200  # seconds in a period (20 minutes)


def format_game_time(t: float) -> str:
    """Format an absolute game time as 'Pn m.ss' (period-relative)."""
    current = round(t)
    period = current // PERIOD_LENGTH
    minutes = (current - period * PERIOD_LENGTH) // 60
    seconds = (current - period * PERIOD_LENGTH) % 60
    return f"P{period + 1} {minutes}.{seconds:02d}"


def main() -> None:
    root = tk.Tk()
    root.title("Game Time")
    root.resizable(False, False)

    entry_var = tk.StringVar()
    result_var = tk.StringVar(value="—")

    def update(*_args) -> None:
        raw = entry_var.get().strip().replace(",", ".")
        if not raw:
            result_var.set("—")
            return
        try:
            seconds = float(raw)
        except ValueError:
            result_var.set("not a number")
            return
        if seconds < 0:
            result_var.set("—")
            return
        result_var.set(format_game_time(seconds))

    entry_var.trace_add("write", update)

    frame = tk.Frame(root, padx=24, pady=20)
    frame.pack()

    tk.Label(frame, text="Game time (seconds)", font=("TkDefaultFont", 10)).pack(anchor="w")

    entry = tk.Entry(frame, textvariable=entry_var, font=("TkFixedFont", 18), width=14,
                     justify="center")
    entry.pack(pady=(4, 14))

    tk.Label(frame, textvariable=result_var, font=("TkDefaultFont", 28, "bold"),
             width=12).pack()

    entry.focus_set()
    root.bind("<Escape>", lambda _e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
