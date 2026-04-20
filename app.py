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

from flask import Flask, render_template, abort, jsonify, redirect, url_for

app = Flask(__name__)

from filter_api import filter_bp
app.register_blueprint(filter_bp)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
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
    try:
        entries = sorted(os.listdir(str(root)))
    except OSError:
        return []
    ids = []
    for name in entries:
        if name.isdigit():
            game_dir = root / name
            try:
                if "game-info.json" in os.listdir(str(game_dir)):
                    ids.append(int(name))
            except OSError:
                pass
    return ids


def _game_exists(game_id: int) -> bool:
    root = _data_root()
    if root is None:
        return False
    game_dir = root / str(game_id)
    return game_dir.is_dir() and (game_dir / "game-info.json").exists()


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
    from hockey.visualize.shift_toi import plot_shift_toi_with_grades
    fig = plot_shift_toi_with_grades(game=game, filename=None)
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    data_configured = _data_root() is not None
    game_ids = _list_game_ids()
    leagues = []
    if data_configured:
        from filter_api import _load_leagues
        leagues = _load_leagues()
    return render_template("index.html",
                           game_ids=game_ids,
                           data_configured=data_configured,
                           has_leagues=len(leagues) > 0)


@app.route("/game/<int:game_id>/confirm-download")
def confirm_download(game_id: int):
    return render_template("confirm_download.html", game_id=game_id)


@app.route("/game/<int:game_id>/download", methods=["POST"])
def download_game(game_id: int):
    root = _data_root()
    if root is None:
        return render_template("confirm_download.html", game_id=game_id,
                               error="DATA_ROOT_DIR is not configured.")
    try:
        from hockey.data_collection.sportlogiq_api import download_complete_game
        download_complete_game(game_id, root_dir=root, verbose=True)
    except EnvironmentError as e:
        return render_template("confirm_download.html", game_id=game_id, error=str(e))
    except Exception as e:
        return render_template("confirm_download.html", game_id=game_id,
                               error=f"Download failed: {e}")
    return redirect(url_for("game_view", game_id=game_id))


@app.route("/game/<int:game_id>")
def game_view(game_id: int):
    if not _game_exists(game_id):
        return redirect(url_for("confirm_download", game_id=game_id))
    game = _load_game(game_id)
    if game is None:
        abort(404, description=f"Game {game_id} could not be loaded.")

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
