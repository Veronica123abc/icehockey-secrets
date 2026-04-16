"""
Ice Hockey Time-on-Ice Dashboard
=================================
Generates an interactive HTML file visualising:
  - Home team average TOI curve (above axis)
  - Away team average TOI curve (negated, below axis)
  - Difference curve  (home - away)
  - Scoring chances as vertical lines + coloured dots

Usage
-----
    from hockey_toi import plot_toi

    plot_toi(
        home_toi   = [...],   # list of 3600 floats  (seconds 1-3600)
        away_toi   = [...],   # list of 3600 floats
        home_chances = [('A', 423), ('B', 1102), ...],  # (grade, second) pairs
        away_chances = [('B', 612),  ('C', 2210), ...],
        output_file = "game_toi.html",
    )

Grades
------
  'A'  →  gold   (#f5c842)
  'B'  →  purple (#a78bfa)
  'C'  →  gray   (#9ca3af)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import plotly.graph_objects as go
import time
from hockey.model.game import Game
from hockey.model.toi import ToIInterval
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from collections import defaultdict
from hockey.io.raw_competition import RawCompetition
from hockey.normalize.build_game import  build_game
from hockey.normalize.build_competition import build_competition
from hockey.model.game import Game
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from hockey.derive.current_shift_series import find_intervals, find_intervals, current_shift_toi_series
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

GRADE_COLORS = {"A": "#f5c842", "B": "#a78bfa", "C": "#9ca3af"}
HOME_COLOR   = "#4fa3e0"
AWAY_COLOR   = "#e06b4f"
DIFF_COLOR   = "#7ed4a0"
BG_COLOR     = "#111827"
GRID_COLOR   = "#1f2937"
TEXT_COLOR   = "#9ca3af"

CHANCE_LINE_HEIGHT = 0.12   # fraction of TOI axis  (lines extend ± from 0)
DOWNSAMPLE = 30             # average every N seconds before plotting


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _downsample(arr: list[float], step: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (x_seconds, y_averaged) with one point per `step` seconds."""
    a = np.array(arr, dtype=float)
    n_bins = len(a) // step
    a = a[: n_bins * step].reshape(n_bins, step)
    y = a.mean(axis=1)
    x = np.arange(step // 2, n_bins * step, step)          # centre of each bin
    return x, y


def _seconds_to_mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _period_boundaries(total_seconds: int = 3600, n_periods: int = 3):
    period_len = total_seconds // n_periods
    return [i * period_len for i in range(n_periods + 1)]


# ---------------------------------------------------------------------------
# main function
# ---------------------------------------------------------------------------

def plot_toi(
    home_toi: list[float],
    away_toi: list[float],
    home_chances: list[tuple[str, int]],
    away_chances:  list[tuple[str, int]],
    output_file: str = "game_toi.html",
    title: str = "Time on Ice — Game Overview",
    downsample: int = DOWNSAMPLE,
    chance_line_height: float = CHANCE_LINE_HEIGHT,
) -> None:
    """
    Parameters
    ----------
    home_toi        : list of floats, length = game seconds (e.g. 3600)
    away_toi        : same, for the away team
    home_chances    : list of (grade, second) — grade in {'A','B','C'}
    away_chances    : same, for the away team
    output_file     : path to write the HTML file
    title           : chart title shown in the HTML
    downsample      : bin size in seconds for the TOI curves
    chance_line_height : how tall the chance lines are in TOI units
    """
    assert len(home_toi) == len(away_toi), "TOI arrays must have the same length"

    total_sec = len(home_toi)

    # --- downsample curves ---------------------------------------------------
    x, h_y  = _downsample(home_toi, downsample)
    _,  a_y = _downsample(away_toi, downsample)
    d_y = h_y - a_y

    x_labels = [_seconds_to_mmss(s) for s in x]

    # --- figure --------------------------------------------------------------
    fig = go.Figure()

    # zero line
    fig.add_hline(y=0, line_width=1, line_color=GRID_COLOR)

    # period dividers
    for sec in _period_boundaries(total_sec)[1:-1]:
        fig.add_vline(
            x=_seconds_to_mmss(sec),
            line_width=1,
            line_dash="dot",
            line_color="#374151",
            annotation_text=f"P{sec // (total_sec // 3) + 1}",
            annotation_font_color=TEXT_COLOR,
            annotation_font_size=11,
        )

    # difference curve (drawn first → behind)
    fig.add_trace(go.Scatter(
        x=x_labels, y=d_y,
        name="Difference (home − away)",
        mode="lines",
        line=dict(color=DIFF_COLOR, width=1.5, dash="dash"),
        hovertemplate="%{x}  diff: %{y:.1%}<extra></extra>",
    ))

    # home TOI
    fig.add_trace(go.Scatter(
        x=x_labels, y=h_y,
        name="Home TOI",
        mode="lines",
        line=dict(color=HOME_COLOR, width=2),
        hovertemplate="%{x}  home: %{y:.1%}<extra></extra>",
    ))

    # away TOI (negated)
    fig.add_trace(go.Scatter(
        x=x_labels, y=-a_y,
        name="Away TOI (negated)",
        mode="lines",
        line=dict(color=AWAY_COLOR, width=2),
        hovertemplate="%{x}  away: %{customdata:.1%}<extra></extra>",
        customdata=a_y,
    ))

    # --- scoring chances -----------------------------------------------------
    def _add_chances(chances, is_home):
        color  = HOME_COLOR if is_home else AWAY_COLOR
        sign   = 1 if is_home else -1
        label  = "Home chance" if is_home else "Away chance"
        shown_grades = set()

        for grade, sec in chances:
            if sec < 0 or sec >= total_sec:
                continue

            dot_color  = GRADE_COLORS.get(grade, "#9ca3af")
            x_label    = _seconds_to_mmss(sec)
            y_top      = sign * chance_line_height

            # vertical line from 0 → dot
            fig.add_trace(go.Scatter(
                x=[x_label, x_label],
                y=[0, y_top],
                mode="lines",
                line=dict(color=color, width=1.5),
                showlegend=False,
                hoverinfo="skip",
            ))

            # dot at tip
            show = grade not in shown_grades
            shown_grades.add(grade)
            fig.add_trace(go.Scatter(
                x=[x_label],
                y=[y_top],
                mode="markers",
                marker=dict(color=dot_color, size=8),
                name=f"Grade {grade}",
                legendgroup=f"grade_{grade}",
                showlegend=show,
                hovertemplate=(
                    f"{'Home' if is_home else 'Away'} chance<br>"
                    f"Grade: {grade}<br>Time: {x_label}<extra></extra>"
                ),
            ))

    _add_chances(home_chances, is_home=True)
    _add_chances(away_chances, is_home=False)

    # --- layout --------------------------------------------------------------
    y_range = max(h_y.max(), a_y.max()) * 1.4

    fig.update_layout(
        title=dict(text=title, font=dict(size=18, color="#f9fafb"), x=0.02),
        paper_bgcolor=BG_COLOR,
        plot_bgcolor=BG_COLOR,
        font=dict(family="system-ui, sans-serif", color=TEXT_COLOR, size=12),
        hovermode="x unified",
        legend=dict(
            bgcolor="#1f2937",
            bordercolor="#374151",
            borderwidth=1,
            font=dict(color=TEXT_COLOR),
        ),
        xaxis=dict(
            title="Game time",
            gridcolor=GRID_COLOR,
            showgrid=True,
            tickangle=0,
            nticks=13,
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Avg TOI",
            gridcolor=GRID_COLOR,
            showgrid=True,
            range=[-y_range, y_range],
            tickformat=".0%",
            tickfont=dict(size=11),
            zeroline=False,
        ),
        margin=dict(l=60, r=30, t=60, b=60),
        height=500,
    )

    fig.write_html(output_file, include_plotlyjs="cdn")
    print(f"Saved → {output_file}")


# ---------------------------------------------------------------------------
# demo — generates sample data and opens the chart
# ---------------------------------------------------------------------------

def _generate_sample_data(total_seconds: int = 3600, seed: int = 42):
    rng = np.random.default_rng(seed)

    def _walk(base, amp, noise):
        vals, v = [], base
        for i in range(total_seconds):
            v += np.sin(i * 0.01) * 0.002 + rng.uniform(-noise, noise)
            v = np.clip(v, base - amp, base + amp)
            vals.append(float(v))
        return vals

    home_toi = _walk(0.55, 0.08, 0.002)
    away_toi = _walk(0.52, 0.08, 0.002)

    grades = ["A", "A", "B", "B", "B", "C"]
    home_chances = [
        (rng.choice(grades), int(rng.integers(0, total_seconds)))
        for _ in range(18)
    ]
    away_chances = [
        (rng.choice(["A", "B", "B", "C", "C"]), int(rng.integers(0, total_seconds)))
        for _ in range(14)
    ]

    return home_toi, away_toi, home_chances, away_chances


if __name__ == "__main__":
    raw = RawGame(game_id=202401, root_dir=settings.data_root_dir)
    game = build_game(raw)
    end_time = 3600
    times = list(range(end_time))
    line_toi = game.shift_toi_series(range(end_time))
    home_mean = [t[game.info.home_team.id]['average_team_shift_toi'] for t in line_toi]
    away_mean = [t[game.info.away_team.id]['average_team_shift_toi'] for t in line_toi]
    diff = [h - a for h, a in zip(home_mean, away_mean)]
    home_toi, away_toi, home_chances, away_chances = _generate_sample_data()

    plot_toi(
        home_toi=home_toi,
        away_toi=away_toi,
        home_chances=home_chances,
        away_chances=away_chances,
        output_file="game_toi.html",
    )