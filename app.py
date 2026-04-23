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
import logging
import os
from pathlib import Path

from flask import Flask, render_template, abort, jsonify, redirect, url_for, request

logger = logging.getLogger(__name__)

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

_game_ids_cache: list[int] | None = None
_game_cache: dict[int, object] = {}
_plotly_cache: dict[int, str] = {}


def _db_conn():
    """Open a fresh DB connection when Azure credentials are available, else None."""
    host = os.getenv("DATABASE_HOST_AZURE")
    if not host:
        return None
    try:
        import mysql.connector
        return mysql.connector.connect(
            host=host,
            user=os.environ["DATABASE_USERNAME_AZURE"],
            password=os.environ["DATABASE_PWD_AZURE"],
            database=os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
            auth_plugin="mysql_native_password",
        )
    except Exception:
        return None


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
    global _game_ids_cache
    if _game_ids_cache is not None:
        return _game_ids_cache
    conn = _db_conn()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT sl_id FROM game ORDER BY sl_id")
            ids = [row[0] for row in cursor.fetchall()]
            cursor.close()
            _game_ids_cache = ids
            return ids
        except Exception:
            return []
        finally:
            conn.close()
    root = _data_root()
    if root is None:
        return []
    ids = []
    try:
        with os.scandir(str(root)) as it:
            for entry in it:
                if entry.is_dir() and entry.name.isdigit():
                    if (root / entry.name / "game-info.json").exists():
                        ids.append(int(entry.name))
    except OSError:
        return []
    _game_ids_cache = sorted(ids)
    return _game_ids_cache


def _invalidate_game_caches(game_id: int) -> None:
    global _game_ids_cache
    _game_ids_cache = None
    _game_cache.pop(game_id, None)
    _plotly_cache.pop(game_id, None)


def _game_exists(game_id: int) -> bool:
    if _game_ids_cache is not None:
        return game_id in _game_ids_cache
    conn = _db_conn()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM game WHERE sl_id = %s LIMIT 1", (game_id,))
            exists = cursor.fetchone() is not None
            cursor.close()
            if exists:
                return True
        except Exception:
            pass
        finally:
            conn.close()
    root = _data_root()
    if root is None:
        return False
    game_dir = root / str(game_id)
    return game_dir.is_dir() and (game_dir / "game-info.json").exists()


def _load_game(game_id: int):
    if game_id in _game_cache:
        logger.info("game %s: cache hit", game_id)
        return _game_cache[game_id]
    conn = _db_conn()
    if conn is not None:
        try:
            from hockey.normalize.build_game_db import build_game_from_db
            game = build_game_from_db(game_id, conn)
            _game_cache[game_id] = game
            logger.info("game %s: loaded from database", game_id)
            return game
        except Exception as e:
            logger.warning("game %s: db load failed (%s), falling back to filesystem", game_id, e)
        finally:
            conn.close()
    root = _data_root()
    if root is None:
        return None
    try:
        from hockey.io.raw_game import RawGame
        from hockey.normalize.build_game import build_game
        raw = RawGame(game_id=game_id, root_dir=root)
        game = build_game(raw)
        _game_cache[game_id] = game
        logger.info("game %s: loaded from filesystem", game_id)
        return game
    except Exception:
        return None


def _build_plotly_html(game) -> str:
    game_id = game.info.game_id
    if game_id in _plotly_cache:
        return _plotly_cache[game_id]
    from hockey.visualize.shift_toi import plot_shift_toi_with_grades
    fig = plot_shift_toi_with_grades(game=game, filename=None)
    html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    _plotly_cache[game_id] = html
    return html


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", data_configured=_data_root() is not None)


@app.route("/game/<int:game_id>/confirm-download")
def confirm_download(game_id: int):
    auto = request.args.get("auto") == "1"
    return render_template("confirm_download.html", game_id=game_id, auto=auto)


@app.route("/game/<int:game_id>/download", methods=["POST"])
def download_game(game_id: int):
    root = _data_root()
    if root is None:
        return render_template("confirm_download.html", game_id=game_id,
                               error="DATA_ROOT_DIR is not configured.")
    try:
        from hockey.data_collection.sportlogiq_api import download_complete_game
        download_complete_game(game_id, root_dir=root, verbose=True)
        _invalidate_game_caches(game_id)
    except EnvironmentError as e:
        return render_template("confirm_download.html", game_id=game_id, error=str(e))
    except Exception as e:
        return render_template("confirm_download.html", game_id=game_id,
                               error=f"Download failed: {e}")
    return redirect(url_for("game_view", game_id=game_id))


@app.route("/game/<int:game_id>")
def game_view(game_id: int):
    if not _game_exists(game_id):
        auto = request.args.get("auto", "0")
        return redirect(url_for("confirm_download", game_id=game_id, auto=auto))
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
