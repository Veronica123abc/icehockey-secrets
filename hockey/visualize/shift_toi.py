from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import plotly.graph_objects as go

from hockey.model.game import Game
from hockey.model.toi import ToIInterval


def _game_end_time_seconds(game: Game, default: int = 3600) -> int:
    # Prefer max event time if available; fall back to 3600.
    if game.events:
        return int(np.ceil(max(e.t for e in game.events)))
    # If no events, try TOI:
    if game.toi:
        end_candidates = [x.end_t for x in game.toi if x.end_t is not None]
        if end_candidates:
            return int(np.ceil(max(end_candidates)))
    return default


def _whistle_times(game: Game) -> list[float]:
    # Using your current normalized event convention: whistle is an event with type == "whistle"
    ts = [e.t for e in game.events if getattr(e, "type", None) == "whistle"]
    ts.sort()
    return ts


def _last_whistle_at_or_before(whistles: list[float], t: float) -> Optional[float]:
    # whistles sorted ascending
    last = None
    for w in whistles:
        if w <= t:
            last = w
        else:
            break
    return last


def _is_goalie(game: Game, player_id: int) -> bool:
    p = game.roster.players.get(player_id)
    return (p is not None) and (p.position == "G")


def mean_shift_time_series(
    *,
    game: Game,
    end_time: int,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
      times: seconds [0..end_time]
      home_mean: mean shift time for home skaters (positive)
      away_mean: mean shift time for away skaters (negative)
    """
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id

    whistles = _whistle_times(game) if reset_on_whistle else []

    times = np.arange(0, end_time + 1, dtype=float)
    home_mean = np.zeros_like(times)
    away_mean = np.zeros_like(times)

    # Split TOI intervals by team for cheaper filtering
    by_team: dict[int, list[ToIInterval]] = {home_id: [], away_id: []}
    for x in game.toi:
        if x.team_id in by_team:
            if (not include_goalies) and _is_goalie(game, x.player_id):
                continue
            by_team[x.team_id].append(x)

    for idx, t in enumerate(times):
        w = _last_whistle_at_or_before(whistles, t) if reset_on_whistle else None

        for team_id, target in ((home_id, "home"), (away_id, "away")):
            vals: list[float] = []
            for x in by_team[team_id]:
                if x.start_t <= t and (x.end_t is None or t < x.end_t):
                    effective_start = x.start_t
                    if w is not None and w > effective_start:
                        effective_start = w
                    vals.append(float(t - effective_start))

            m = float(np.mean(vals)) if vals else 0.0
            if target == "home":
                home_mean[idx] = m
            else:
                away_mean[idx] = -m  # away below axis

    return times, home_mean, away_mean


def plot_shift_toi_with_grades(
    *,
    game: Game,
    filename: str = "shift_toi.html",
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> go.Figure:
    end_time = _game_end_time_seconds(game, default=3600)

    times, home_mean, away_mean = mean_shift_time_series(
        game=game,
        end_time=end_time,
        include_goalies=include_goalies,
        reset_on_whistle=reset_on_whistle,
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=times,
            y=home_mean,
            mode="lines",
            name="Home mean shift TOI",
            line=dict(color="royalblue", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=away_mean,
            mode="lines",
            name="Away mean shift TOI",
            line=dict(color="firebrick", width=2),
        )
    )

    # Grade markers (A/B/C) + vertical line at event time
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id

    graded = [
        e for e in game.events
        if getattr(e, "grade", None) in {"A", "B", "C"}
    ]

    # Put grade labels above/below plot with a bit of padding
    y_top = float(np.max(home_mean)) if len(home_mean) else 0.0
    y_bottom = float(np.min(away_mean)) if len(away_mean) else 0.0
    pad = max(5.0, 0.1 * max(y_top, abs(y_bottom), 1.0))

    shapes = []
    home_x, home_y, home_text = [], [], []
    away_x, away_y, away_text = [], [], []

    for e in graded:
        x = float(e.t)

        shapes.append(
            dict(
                type="line",
                x0=x, x1=x,
                y0=y_bottom - pad, y1=y_top + pad,
                line=dict(color="orange", width=2),
            )
        )

        team = getattr(e, "team_id_in_possession", None)
        grade = getattr(e, "grade", "")

        if team == home_id:
            home_x.append(x)
            home_y.append(y_top + pad * 0.5)
            home_text.append(f"{grade} (H)")
        elif team == away_id:
            away_x.append(x)
            away_y.append(y_bottom - pad * 0.5)
            away_text.append(f"{grade} (A)")
        else:
            # If team is unknown/None, skip labeling (still keeps vertical line)
            pass

    if home_x:
        fig.add_trace(
            go.Scatter(
                x=home_x,
                y=home_y,
                mode="markers+text",
                text=home_text,
                textposition="middle center",
                marker=dict(size=18, color="black", line=dict(width=3, color="royalblue")),
                name="Grades (home)",
                showlegend=True,
            )
        )

    if away_x:
        fig.add_trace(
            go.Scatter(
                x=away_x,
                y=away_y,
                mode="markers+text",
                text=away_text,
                textposition="middle center",
                marker=dict(size=18, color="black", line=dict(width=3, color="firebrick")),
                name="Grades (away)",
                showlegend=True,
            )
        )

    fig.update_layout(
        title="Mean current shift time on ice (skaters) + graded events",
        xaxis=dict(title="Game time (s)", range=[0, end_time]),
        yaxis=dict(title="Mean current shift TOI (s)", zeroline=True, zerolinewidth=1, zerolinecolor="gray"),
        shapes=shapes,
        height=800,
        hovermode="x unified",
    )

    fig.write_html(filename, auto_open=False)
    return fig