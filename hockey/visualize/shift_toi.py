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
from hockey.derive.current_shift_series import find_intervals, find_intervals, current_shift_toi_series
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
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
    marker_size = 50
    marker_line_width = 3
    marker_text_size = 25

    marker_y_spacing = 25
    marker_min_x_spacing = 25
    chance_colors = {"A": "green",
                     "B": "orange",
                     "C": "red"}

    end_time = _game_end_time_seconds(game, default=3600)
    times = list(range(end_time))
    line_toi = game.shift_toi_series(range(end_time))
    home_mean = [t[game.info.home_team.id]['average_team_shift_toi'] for t in line_toi]
    away_mean = [t[game.info.away_team.id]['average_team_shift_toi'] for t in line_toi]
    diff =[h-a for h,a in zip(home_mean, away_mean)]
    fig = go.Figure()

    home_name = game.info.home_team.display_name
    away_name = game.info.away_team.display_name
    fig.add_trace(
        go.Scatter(
            x=times,
            y=home_mean,
            mode="lines",
            name=f"{home_name} mean shift TOI",
            hovertemplate="%{y:.0f} s<extra></extra>",
            line=dict(color="royalblue", width=2),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=times,
            y=[-t for t in away_mean],
            mode="lines",
            name=f"{away_name} mean shift TOI",
            hovertext = [f"{y:.0f}" for y in away_mean],
            hovertemplate="%{hovertext} s<extra></extra>",
            line=dict(color="firebrick", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=diff,
            mode="lines",
            name=f"Difference ({home_name} - {away_name})",
            hovertemplate="%{y:.0f} s<extra></extra>",
            line=dict(color="black", width=3),
        )
    )

    # Grade markers (A/B/C) + vertical line at event time
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id

    graded = [
        e for e in game.events
        if getattr(e, "grade", None) in {"A", "B", "C"} and
           e.raw['team_skaters_on_ice'] == 5 and e.raw['opposing_team_skaters_on_ice'] == 5
    ]

    # Put grade labels above/below plot with a bit of padding
    y_top = float(np.max(home_mean)) if len(home_mean) else 0.0
    y_bottom = -float(np.max(away_mean)) if len(away_mean) else 0.0
    pad = 0 #max(5.0, 0.1 * max(y_top, abs(y_bottom), 1.0))

    shapes = []
    home_x, home_y, home_text, home_marker_color, home_hoover_text = [], [], [], [], []
    away_x, away_y, away_text, away_marker_color, away_hoover_text = [], [], [], [], []


    for e in graded:
        x = float(e.t)
        team = getattr(e, "team_id_in_possession", None)
        grade = getattr(e, "grade", "")

        if team == home_id:
            home_x.append(x)
            home_y.append(y_top + pad * 0.5)
            home_text.append(f"{grade}")
            home_marker_color.append(chance_colors[grade])
            current_time = round(x)
            period = current_time // 1200
            minutes = (current_time - period * 1200) // 60
            seconds = (current_time - period * 1200) % 60
            time_str = f"{minutes}.{seconds:02d}"
            home_hoover_text.append(f"P{period+1} {time_str}")

        elif team == away_id:
            away_x.append(x)
            away_y.append(y_bottom - pad * 0.5)
            away_text.append(f"{grade}")
            away_marker_color.append(chance_colors[grade])
            current_time = round(x)
            period = current_time // 1200
            minutes = (current_time - period * 1200) // 60
            seconds = (current_time - period * 1200) % 60
            time_str = f"{minutes}.{seconds:02d}"
            away_hoover_text.append(f"P{period+1} {time_str}")
        else:
            # If team is unknown/None, skip labeling (still keeps vertical line)
            pass



    y_offset = 0
    for i in range(1, len(home_x)):
        if home_x[i] - home_x[i-1] < marker_min_x_spacing:
            y_offset += marker_y_spacing
            home_y[i] += y_offset
        else:
            y_offset = 0

    y_offset = 0
    for i in range(1, len(away_x)):
        if away_x[i] - away_x[i-1] < marker_min_x_spacing:
            y_offset += marker_y_spacing
            away_y[i] += y_offset
        else:
            y_offset = 0

    for c_idx in range(len(home_x)):
        shapes.append(
            dict(
                type="line",
                name=f"{home_text[c_idx]}",
                x0=home_x[c_idx], x1=home_x[c_idx],
                y0=0, y1=home_y[c_idx] -10,
                line=dict(color=home_marker_color[c_idx], width=2),
                showlegend=False,
            )
        )

    for c_idx in range(len(away_x)):
        shapes.append(
            dict(
                type="line",
                name=f"{away_text[c_idx]}",
                x0=away_x[c_idx], x1=away_x[c_idx],
                y0=0, y1=away_y[c_idx],
                line=dict(color=away_marker_color[c_idx], width=2),
                showlegend=False,
            )
        )


    if home_x:
        fig.add_trace(
            go.Scatter(
                x=home_x,
                y=home_y,
                mode="markers+text",
                text=home_text,
                textfont=dict(color=home_marker_color, size=marker_text_size),
                textposition="middle center",
                hovertext=home_hoover_text,
                hovertemplate="%{hovertext}<extra></extra>",
                marker=dict(size=marker_size, color="black", line=dict(width=marker_line_width, color = home_marker_color)),#="firebrick")),
                name=f"Grades ({home_name})",
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
                textfont=dict(color=away_marker_color, size=marker_text_size),
                textposition="middle center",
                hovertext=away_hoover_text,
                hovertemplate="%{hovertext}<extra></extra>",
                marker=dict(size=marker_size, color="black", line=dict(width=marker_line_width, color=away_marker_color)),
                name=f"Grades ({away_name})",
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


if __name__ == "__main__":
    raw = RawGame(game_id=202401, root_dir=settings.data_root_dir)
    game = build_game(raw)
    #intervals = [(shift.start_t, shift.end_t) for shift in game.toi]
    #queries = list(set([shift.start_t for shift in game.toi]))
    #queries = range(3600)
    #toi = game.shift_toi_series(queries)
    plot_shift_toi_with_grades(game=game, filename="shift_toi.html")