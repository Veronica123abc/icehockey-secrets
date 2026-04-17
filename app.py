"""
Ice Hockey Analytics — Azure Web App
=====================================
Flask application serving interactive game visualizations and analytics
from the hockey module.

Run locally:
    flask run --debug

Deploy to Azure Web App:
    Configured via startup.sh with gunicorn.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, render_template, abort, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# DATA_ROOT_DIR can be set via Azure App Settings or .env
_PROJECT_ROOT = Path(__file__).resolve().parent
_dotenv_path = _PROJECT_ROOT / ".env"
if _dotenv_path.exists():
    for line in _dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

DATA_ROOT_DIR = os.getenv("DATA_ROOT_DIR", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_root() -> Path | None:
    d = os.getenv("DATA_ROOT_DIR", DATA_ROOT_DIR)
    if not d:
        return None
    p = Path(d).expanduser()
    if p.exists() and p.is_dir():
        return p
    return None


def _list_game_ids() -> list[int]:
    root = _data_root()
    if root is None:
        return []
    ids = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.isdigit():
            if (child / "game-info.json").exists():
                ids.append(int(child.name))
    return ids


def _load_game(game_id: int):
    root = _data_root()
    if root is None:
        return None
    try:
        from hockey.io.raw_game import RawGame
        from hockey.normalize.build_game import build_game

        raw = RawGame(game_id=game_id, root_dir=root)
        return build_game(raw)
    except Exception:
        return None


def _build_plotly_html(game) -> str:
    import plotly.graph_objects as go
    import numpy as np

    end_time = 3600
    if game.events:
        end_time = int(np.ceil(max(e.t for e in game.events)))

    times = list(range(end_time))
    line_toi = game.shift_toi_series(range(end_time))
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    home_name = game.info.home_team.display_name
    away_name = game.info.away_team.display_name

    home_mean = [t[home_id]["average_team_shift_toi"] for t in line_toi]
    away_mean = [t[away_id]["average_team_shift_toi"] for t in line_toi]
    diff = [h - a for h, a in zip(home_mean, away_mean)]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=times, y=home_mean,
        mode="lines",
        name=f"{home_name} mean shift TOI",
        hovertemplate="%{y:.0f} s<extra></extra>",
        line=dict(color="royalblue", width=2),
    ))

    fig.add_trace(go.Scatter(
        x=times, y=[-t for t in away_mean],
        mode="lines",
        name=f"{away_name} mean shift TOI",
        hovertext=[f"{y:.0f}" for y in away_mean],
        hovertemplate="%{hovertext} s<extra></extra>",
        line=dict(color="firebrick", width=2),
    ))

    fig.add_trace(go.Scatter(
        x=times, y=diff,
        mode="lines",
        name=f"Difference ({home_name} - {away_name})",
        hovertemplate="%{y:.0f} s<extra></extra>",
        line=dict(color="black", width=3),
    ))

    chance_colors = {"A": "green", "B": "orange", "C": "red"}
    marker_size = 50
    marker_line_width = 3
    marker_text_size = 25
    marker_y_spacing = 25
    marker_min_x_spacing = 25

    graded = [
        e for e in game.events
        if getattr(e, "grade", None) in {"A", "B", "C"}
        and e.raw.get("team_skaters_on_ice") == 5
        and e.raw.get("opposing_team_skaters_on_ice") == 5
    ]

    y_top = float(np.max(home_mean)) if home_mean else 0.0
    y_bottom = -float(np.max(away_mean)) if away_mean else 0.0

    shapes = []
    home_x, home_y, home_text, home_mc, home_ht = [], [], [], [], []
    away_x, away_y, away_text, away_mc, away_ht = [], [], [], [], []

    for e in graded:
        x = float(e.t)
        team = getattr(e, "team_id_in_possession", None)
        grade = getattr(e, "grade", "")
        current_time = round(x)
        period = current_time // 1200
        minutes = (current_time - period * 1200) // 60
        seconds = (current_time - period * 1200) % 60
        time_str = f"P{period + 1} {minutes}.{seconds:02d}"

        if team == home_id:
            home_x.append(x)
            home_y.append(y_top)
            home_text.append(grade)
            home_mc.append(chance_colors[grade])
            home_ht.append(time_str)
        elif team == away_id:
            away_x.append(x)
            away_y.append(y_bottom)
            away_text.append(grade)
            away_mc.append(chance_colors[grade])
            away_ht.append(time_str)

    y_offset = 0
    for i in range(1, len(home_x)):
        if home_x[i] - home_x[i - 1] < marker_min_x_spacing:
            y_offset += marker_y_spacing
            home_y[i] += y_offset
        else:
            y_offset = 0

    y_offset = 0
    for i in range(1, len(away_x)):
        if away_x[i] - away_x[i - 1] < marker_min_x_spacing:
            y_offset += marker_y_spacing
            away_y[i] += y_offset
        else:
            y_offset = 0

    for idx in range(len(home_x)):
        shapes.append(dict(
            type="line", x0=home_x[idx], x1=home_x[idx],
            y0=0, y1=home_y[idx] - 10,
            line=dict(color=home_mc[idx], width=2),
        ))

    for idx in range(len(away_x)):
        shapes.append(dict(
            type="line", x0=away_x[idx], x1=away_x[idx],
            y0=0, y1=away_y[idx],
            line=dict(color=away_mc[idx], width=2),
        ))

    if home_x:
        fig.add_trace(go.Scatter(
            x=home_x, y=home_y, mode="markers+text",
            text=home_text,
            textfont=dict(color=home_mc, size=marker_text_size),
            textposition="middle center",
            hovertext=home_ht,
            hovertemplate="%{hovertext}<extra></extra>",
            marker=dict(size=marker_size, color="black",
                        line=dict(width=marker_line_width, color=home_mc)),
            name=f"Grades ({home_name})",
        ))

    if away_x:
        fig.add_trace(go.Scatter(
            x=away_x, y=away_y, mode="markers+text",
            text=away_text,
            textfont=dict(color=away_mc, size=marker_text_size),
            textposition="middle center",
            hovertext=away_ht,
            hovertemplate="%{hovertext}<extra></extra>",
            marker=dict(size=marker_size, color="black",
                        line=dict(width=marker_line_width, color=away_mc)),
            name=f"Grades ({away_name})",
        ))

    fig.update_layout(
        title=f"{home_name} vs {away_name} — Mean shift TOI + graded chances",
        xaxis=dict(title="Game time (s)", range=[0, end_time]),
        yaxis=dict(title="Mean current shift TOI (s)",
                   zeroline=True, zerolinewidth=1, zerolinecolor="gray"),
        shapes=shapes,
        height=700,
        hovermode="x unified",
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    game_ids = _list_game_ids()
    data_configured = _data_root() is not None
    return render_template("index.html",
                           game_ids=game_ids,
                           data_configured=data_configured)


@app.route("/game/<int:game_id>")
def game_view(game_id: int):
    game = _load_game(game_id)
    if game is None:
        abort(404, description=f"Game {game_id} not found or data not configured.")

    chart_html = _build_plotly_html(game)

    info = {
        "game_id": game.info.game_id,
        "home_team": game.info.home_team.display_name,
        "away_team": game.info.away_team.display_name,
        "num_events": len(game.events),
        "num_toi_intervals": len(game.toi),
        "num_players": len(game.roster.players),
    }
    return render_template("game.html", info=info, chart_html=chart_html)


@app.route("/api/games")
def api_games():
    return jsonify({"games": _list_game_ids()})


@app.route("/api/game/<int:game_id>")
def api_game(game_id: int):
    game = _load_game(game_id)
    if game is None:
        return jsonify({"error": f"Game {game_id} not found"}), 404

    graded = [e for e in game.events
              if getattr(e, "grade", None) in {"A", "B", "C"}]

    return jsonify({
        "game_id": game.info.game_id,
        "home_team": game.info.home_team.display_name,
        "away_team": game.info.away_team.display_name,
        "num_events": len(game.events),
        "num_graded_chances": len(graded),
        "num_players": len(game.roster.players),
    })


@app.route("/api/game/<int:game_id>/events")
def api_game_events(game_id: int):
    game = _load_game(game_id)
    if game is None:
        return jsonify({"error": f"Game {game_id} not found"}), 404

    events = [
        {
            "t": e.t,
            "type": e.type,
            "name": e.name,
            "team_id_in_possession": e.team_id_in_possession,
            "player_id": e.player_id,
            "grade": e.grade,
        }
        for e in game.events
    ]
    return jsonify({"game_id": game_id, "events": events})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
