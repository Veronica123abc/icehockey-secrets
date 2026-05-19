from __future__ import annotations

from collections import defaultdict
from typing import Optional

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hockey.model.game import Game
from hockey.visualize.shift_toi import _team_color, _game_end_time_seconds

XG_VERSION = 3


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _cumulative_xg(game: Game) -> dict[int, tuple[list[float], list[float]]]:
    """Return {team_id: (times, cumulative_xg)} as step-function data points."""
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id

    shots: dict[int, list[tuple[float, float]]] = {home_id: [], away_id: []}
    for e in game.events:
        raw = e.get_raw("expected_goals_all_shots")
        if raw is None or raw == "":
            continue
        try:
            xg = float(raw)
        except (TypeError, ValueError):
            continue
        if xg <= 0:
            continue
        team = e.team_id_in_possession or e.team_id
        if team in shots:
            shots[team].append((e.t, xg))

    result = {}
    for team_id, team_shots in shots.items():
        team_shots.sort()
        times = [0.0]
        cumxg = [0.0]
        running = 0.0
        for t, xg in team_shots:
            running += xg
            times.append(t)
            cumxg.append(running)
        result[team_id] = (times, cumxg)
    return result


def _accumulated_toi(game: Game, end_time: int) -> dict[int, np.ndarray]:
    """Return {player_id: array of length end_time} where [t] = seconds on ice up to t."""
    t_arr = np.arange(end_time, dtype=float)
    by_player: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for x in game.toi:
        end = x.end_t if x.end_t is not None else float(end_time)
        by_player[x.player_id].append((x.start_t, end))
    result = {}
    for pid, intervals in by_player.items():
        acc = np.zeros(end_time)
        for s, e in intervals:
            acc += np.clip(t_arr - s, 0.0, e - s)
        result[pid] = acc
    return result


_POS_ORDER = {"F": 0, "LW": 0, "RW": 0, "C": 0, "D": 1, "G": 2}


def _build_hover_strings(
    game: Game,
    toi_series: list,
    acc_toi: dict[int, np.ndarray],
) -> list[str]:
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    roster = game.roster.players

    def _sort_key(p: dict) -> tuple:
        player = roster.get(p["player_id"])
        pos = player.position if player else ""
        return (_POS_ORDER.get(pos, 0), -p["current_shift_toi"])

    strings = []
    for t_idx, snapshot in enumerate(toi_series):
        lines = []
        for team_id, team_info in [
            (home_id, game.info.home_team),
            (away_id, game.info.away_team),
        ]:
            lines.append(f"<b>{team_info.display_name}</b>")
            players_on_ice = sorted(snapshot[team_id]["players"], key=_sort_key)
            for p in players_on_ice:
                pid = p["player_id"]
                player = roster.get(pid)
                if player and (player.first_name or player.last_name):
                    name = f"{player.first_name or ''} {player.last_name or ''}".strip()
                else:
                    name = str(pid)
                pos = f"({player.position})" if player and player.position else ""
                shift = _fmt(p["current_shift_toi"])
                arr = acc_toi.get(pid)
                total = _fmt(float(arr[t_idx])) if arr is not None else "?"
                lines.append(f"{name} {pos} {shift} / {total}")
        strings.append("<br>".join(lines))
    return strings


def plot_xg_with_toi_diff(
    *,
    game: Game,
    filename: Optional[str] = "xg.html",
) -> go.Figure:
    home = game.info.home_team
    away = game.info.away_team
    home_color = _team_color(home.id, "#60a5fa")
    away_color = _team_color(away.id, "#f87171")

    end_time = _game_end_time_seconds(game)
    num_periods = max(3, (end_time + 1199) // 1200)
    tick_vals = list(range(0, end_time + 1, 300))
    tick_text = [str((t % 1200) // 60) for t in tick_vals]

    xg_data = _cumulative_xg(game)

    toi_times = list(range(end_time))
    toi_series = game.shift_toi_series(toi_times)
    diff = [
        s[home.id]["average_team_shift_toi"] - s[away.id]["average_team_shift_toi"]
        for s in toi_series
    ]
    diff_pos = [max(0.0, v) for v in diff]
    diff_neg = [min(0.0, v) for v in diff]

    acc_toi = _accumulated_toi(game, end_time)
    hover_strings = _build_hover_strings(game, toi_series, acc_toi)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # --- TOI diff ribbon ---
    fig.add_trace(go.Scatter(
        x=toi_times, y=diff_pos,
        fill="tozeroy",
        fillcolor=f"rgba({_hex_to_rgb(home_color)}, 0.10)",
        line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ), secondary_y=True)

    fig.add_trace(go.Scatter(
        x=toi_times, y=diff_neg,
        fill="tozeroy",
        fillcolor=f"rgba({_hex_to_rgb(away_color)}, 0.10)",
        line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ), secondary_y=True)

    # TOI diff line — carries all player hover data via customdata
    fig.add_trace(go.Scatter(
        x=toi_times,
        y=diff,
        mode="lines",
        name="TOI diff (home − away)",
        line=dict(color="rgba(148,163,184,0.40)", width=1.5),
        customdata=[[s] for s in hover_strings],
        hovertemplate="TOI diff: %{y:.0f} s<br>%{customdata[0]}<extra></extra>",
    ), secondary_y=True)

    # --- Cumulative xG step lines ---
    for team_id, color, name in [
        (home.id, home_color, f"{home.display_name} xG"),
        (away.id, away_color, f"{away.display_name} xG"),
    ]:
        t_list, xg_list = xg_data.get(team_id, ([0.0], [0.0]))
        fig.add_trace(go.Scatter(
            x=t_list, y=xg_list,
            mode="lines+markers",
            name=name,
            line=dict(color=color, width=2.5, shape="hv"),
            marker=dict(size=7, color=color, symbol="circle",
                        line=dict(color="#0f172a", width=1)),
            hovertemplate="%{y:.2f} xG<extra>" + name + "</extra>",
        ), secondary_y=False)

    # --- Period shading and dividers ---
    shapes = []
    for p in range(num_periods):
        if p % 2 == 1:
            shapes.append(dict(
                type="rect", xref="x", yref="paper",
                x0=p * 1200, x1=min((p + 1) * 1200, end_time),
                y0=0, y1=1,
                fillcolor="rgba(255,255,255,0.03)",
                line_width=0, layer="below",
            ))
    for p in range(1, num_periods):
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=p * 1200, x1=p * 1200,
            y0=0, y1=1,
            line=dict(color="#334155", width=1, dash="dot"),
        ))

    period_annotations = [
        dict(
            x=(p + 0.5) * 1200, y=1.0, yref="paper",
            text=f"P{p + 1}" if p < 3 else "OT",
            showarrow=False,
            font=dict(color="#475569", size=14),
            xanchor="center", yanchor="bottom",
        )
        for p in range(num_periods)
    ]

    home_total = xg_data[home.id][1][-1] if home.id in xg_data else 0.0
    away_total = xg_data[away.id][1][-1] if away.id in xg_data else 0.0

    fig.update_layout(
        title=dict(
            text=(
                f"{home.display_name} vs {away.display_name} — xG & Shift TOI Diff"
                f"  |  {home_total:.2f} – {away_total:.2f}"
            ),
            font=dict(color="#e2e8f0", size=18),
        ),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#94a3b8", size=14),
        xaxis=dict(
            title=None,
            range=[0, end_time],
            tickvals=tick_vals,
            ticktext=tick_text,
            tickfont=dict(color="#64748b", size=14),
            gridcolor="#1e293b",
            zerolinecolor="#334155",
            showline=False,
        ),
        yaxis=dict(
            title="Cumulative xG",
            titlefont=dict(color="#64748b", size=14),
            tickfont=dict(color="#64748b", size=14),
            gridcolor="#1e293b",
            zeroline=False,
            showline=False,
            rangemode="tozero",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(color="#94a3b8", size=14),
            bgcolor="rgba(0,0,0,0)",
        ),
        shapes=shapes,
        annotations=period_annotations,
        height=650,
        hovermode="x unified",
        margin=dict(t=90, b=50, l=70, r=80),
    )

    fig.update_yaxes(
        title_text="TOI diff (s)",
        titlefont=dict(color="rgba(148,163,184,0.5)", size=14),
        tickfont=dict(color="rgba(148,163,184,0.5)", size=14),
        zeroline=True, zerolinewidth=1, zerolinecolor="#475569",
        gridcolor="rgba(0,0,0,0)",
        showline=False,
        secondary_y=True,
    )

    if filename is not None:
        fig.write_html(filename, auto_open=False)
    return fig


if __name__ == "__main__":
    import os
    from pathlib import Path

    GAME_ID = 54559

    game = None
    host = os.getenv("DATABASE_HOST_AZURE")
    if host:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=host,
                user=os.environ["DATABASE_USERNAME_AZURE"],
                password=os.environ["DATABASE_PWD_AZURE"],
                database=os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
                auth_plugin="mysql_native_password",
            )
            from hockey.normalize.build_game_db import build_game_from_db
            game = build_game_from_db(GAME_ID, conn)
            conn.close()
            print("(loaded from database)")
        except Exception as e:
            print(f"(DB load failed: {e}, falling back to filesystem)")

    if game is None:
        from hockey.io.raw_game import RawGame
        from hockey.normalize.build_game import build_game
        root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
        raw = RawGame(game_id=GAME_ID, root_dir=root)
        game = build_game(raw)
        print("(loaded from filesystem)")

    fig = plot_xg_with_toi_diff(game=game, filename="xg.html")
    print("Written to xg.html")
