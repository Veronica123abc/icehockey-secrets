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
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, abort, jsonify, redirect, url_for, request

from source_mode import game_source, use_db, use_files

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# .env is loaded before filter_api is imported: that module picks its provider
# at import time, and would otherwise decide with DATABASE_HOST_AZURE still
# unset locally. On Azure the App Settings are already in the environment.
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

app = Flask(__name__)

from filter_api import filter_bp  # noqa: E402  (must follow the .env load)
app.register_blueprint(filter_bp)

# Keyed by source mode: the id list differs per backend, so a switch must not
# hand back the previous mode's answer.
_game_ids_cache: dict[str, list[int]] = {}

_chat_logger = logging.getLogger("chat")
_chat_logger.setLevel(logging.INFO)
_chat_handler = logging.FileHandler(_PROJECT_ROOT / "chat.log", encoding="utf-8")
_chat_handler.setFormatter(logging.Formatter("%(message)s"))
_chat_logger.addHandler(_chat_handler)


def _log_chat(question: str, sql: str | None, row_count: int | None, error: str | None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "sql": sql,
        "row_count": row_count,
        "error": error,
    }
    _chat_logger.info(json.dumps(entry, ensure_ascii=False))
# Both caches are bounded LRUs. A cached game costs roughly 20 MB (the Game
# object plus its rendered HTML), and the B1 instance has ~1.75 GB shared
# between two gunicorn workers that each keep their own copy -- unbounded
# growth put a worker into the OOM killer partway through browsing.
#
# GAME_CACHE_SIZE is the number of games to retain per worker; it is read at
# import, so changing it needs a restart (unlike GAME_SOURCE).
def _cache_size(default: int) -> int:
    try:
        return max(1, int(os.getenv("GAME_CACHE_SIZE", "") or default))
    except ValueError:
        return default


_GAME_CACHE_SIZE = _cache_size(5)
# Four figures per game at most: shift_toi, entries, xg, canvas.
_PLOTLY_CACHE_SIZE = _GAME_CACHE_SIZE * 4

# keyed by (game_id, playsequence_source, source mode) -- the canvas needs a
# different source than the analysis pages, so one game can be cached twice.
_game_cache: "OrderedDict[tuple, object]" = OrderedDict()
_plotly_cache: "OrderedDict[tuple, str]" = OrderedDict()


def _cache_get(cache: OrderedDict, key: tuple):
    """Return the cached value and mark it most-recently-used, else None."""
    if key not in cache:
        return None
    cache.move_to_end(key)
    return cache[key]


def _cache_put(cache: OrderedDict, key: tuple, value, maxsize: int):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > maxsize:
        cache.popitem(last=False)


def _db_conn():
    """Open a fresh DB connection when the mode allows it and credentials exist.

    Returns None in ``data_root_only``, which is what keeps every DB branch
    below a single ``if conn is not None`` rather than a mode check of its own.
    """
    if not use_db():
        return None
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
            connect_timeout=5,
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
    mode = game_source()
    cached = _game_ids_cache.get(mode)
    if cached is not None:
        return cached
    conn = _db_conn()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT sl_id FROM game ORDER BY sl_id")
            ids = [row[0] for row in cursor.fetchall()]
            cursor.close()
            _game_ids_cache[mode] = ids
            return ids
        except Exception:
            return []
        finally:
            conn.close()
    if not use_files():
        return []
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
    _game_ids_cache[mode] = sorted(ids)
    return _game_ids_cache[mode]


def _invalidate_game_caches(game_id: int) -> None:
    _game_ids_cache.clear()
    for k in [k for k in _game_cache if isinstance(k, tuple) and k[0] == game_id]:
        del _game_cache[k]
    for k in [k for k in _plotly_cache if isinstance(k, tuple) and k[0] == game_id]:
        del _plotly_cache[k]


def _game_exists(game_id: int) -> bool:
    cached = _game_ids_cache.get(game_source())
    if cached is not None:
        return game_id in cached
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
    if not use_files():
        return False
    root = _data_root()
    if root is None:
        return False
    game_dir = root / str(game_id)
    return game_dir.is_dir() and (game_dir / "game-info.json").exists()


def _load_game(game_id: int, playsequence_source: str | None = None):
    """Load a Game, cached per (game_id, playsequence source, source mode).

    ``playsequence_source=None`` follows the active GAME_SOURCE mode: database
    first, then the filesystem with RawGame's default source, with either half
    skipped under db_only / data_root_only. Naming a source goes straight to
    the filesystem, since the database has no equivalent distinction -- so
    under db_only it finds nothing and the caller falls back to the default
    source. That distinction matters because the two files carry different
    event vocabularies -- playsequence_compiled.json adds the ~19 derived types
    (controlledentry, zoneexit, scoringchance, ...) the game canvas is built
    around, while only the plain file has "whistle".
    """
    cache_key = (game_id, playsequence_source, game_source())
    cached = _cache_get(_game_cache, cache_key)
    if cached is not None:
        app.logger.warning("game %s: cache hit (%s)", game_id, playsequence_source or "default")
        return cached

    if playsequence_source is None:
        conn = _db_conn()
        if conn is not None:
            try:
                from hockey.normalize.build_game_db import build_game_from_db
                game = build_game_from_db(game_id, conn)
                _cache_put(_game_cache, cache_key, game, _GAME_CACHE_SIZE)
                app.logger.warning("game %s: loaded from database", game_id)
                return game
            except Exception as e:
                app.logger.warning("game %s: db load failed (%s), falling back to filesystem", game_id, e)
            finally:
                conn.close()

    if not use_files():
        return None
    root = _data_root()
    if root is None:
        return None
    try:
        from hockey.io.raw_game import RawGame
        from hockey.normalize.build_game import build_game
        kwargs = {} if playsequence_source is None else {"playsequence_source": playsequence_source}
        raw = RawGame(game_id=game_id, root_dir=root, **kwargs)
        game = build_game(raw)
        _cache_put(_game_cache, cache_key, game, _GAME_CACHE_SIZE)
        app.logger.warning("game %s: loaded from filesystem (%s)", game_id,
                           playsequence_source or "default")
        return game
    except Exception:
        return None


def _build_plotly_html(game) -> str:
    from hockey.visualize.shift_toi import plot_shift_toi_with_grades, PLOT_VERSION
    cache_key = (game.info.game_id, "shift_toi", PLOT_VERSION, game_source())
    cached = _cache_get(_plotly_cache, cache_key)
    if cached is not None:
        return cached
    fig = plot_shift_toi_with_grades(game=game, filename=None)
    html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    _cache_put(_plotly_cache, cache_key, html, _PLOTLY_CACHE_SIZE)
    return html


def _build_canvas_html(game) -> str:
    """The game-canvas page. A complete standalone document, not a fragment."""
    from hockey.visualize.game_canvas import GameCanvas, CANVAS_VERSION
    cache_key = (game.info.game_id, "canvas", CANVAS_VERSION, game_source())
    cached = _cache_get(_plotly_cache, cache_key)
    if cached is not None:
        return cached
    html = GameCanvas(game).to_html(back_href=url_for("index"))
    _cache_put(_plotly_cache, cache_key, html, _PLOTLY_CACHE_SIZE)
    return html


def _build_entries_html(game) -> str:
    from hockey.visualize.entries import plot_entries, ENTRIES_VERSION
    cache_key = (game.info.game_id, "entries", ENTRIES_VERSION, game_source())
    cached = _cache_get(_plotly_cache, cache_key)
    if cached is not None:
        return cached
    fig = plot_entries(game=game, filename=None)
    html = fig.to_html(full_html=False, include_plotlyjs=False)
    _cache_put(_plotly_cache, cache_key, html, _PLOTLY_CACHE_SIZE)
    return html


def _build_xg_html(game) -> str:
    from hockey.visualize.xg import plot_xg_with_toi_diff, XG_VERSION
    cache_key = (game.info.game_id, "xg", XG_VERSION, game_source())
    cached = _cache_get(_plotly_cache, cache_key)
    if cached is not None:
        return cached
    fig = plot_xg_with_toi_diff(game=game, filename=None)
    html = fig.to_html(full_html=False, include_plotlyjs=False)
    _cache_put(_plotly_cache, cache_key, html, _PLOTLY_CACHE_SIZE)
    return html


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    db_status = "disabled"
    if use_db() and os.getenv("DATABASE_HOST_AZURE"):
        conn = _db_conn()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                db_status = "ok"
            except Exception as e:
                db_status = f"error: {e}"
            finally:
                conn.close()
        else:
            db_status = "unreachable"
    return jsonify({
        "ok": True,
        "db": db_status,
        "source": game_source(),
        "data_root": _data_root() is not None if use_files() else False,
    })


@app.route("/")
def index():
    return render_template("index.html",
                           data_configured=use_files() and _data_root() is not None)


@app.route("/game/<int:game_id>/confirm-download")
def confirm_download(game_id: int):
    auto = request.args.get("auto") == "1"
    return render_template("confirm_download.html", game_id=game_id, auto=auto)


@app.route("/game/<int:game_id>/download", methods=["POST"])
def download_game(game_id: int):
    if not use_files():
        # The download lands under DATA_ROOT_DIR, which db_only never reads --
        # it would look like a silent no-op.
        return render_template(
            "confirm_download.html", game_id=game_id,
            error="GAME_SOURCE=db_only: downloads go to DATA_ROOT_DIR, which "
                  "this mode does not read. Switch to combined to download.")
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
    entries_html = _build_entries_html(game)
    xg_html = _build_xg_html(game)

    info = {
        "game_id": game.info.game_id,
        "home_team": game.info.home_team.display_name,
        "away_team": game.info.away_team.display_name,
        "num_events": len(game.events),
        "num_toi_intervals": len(game.toi),
        "num_players": len(game.roster.players),
    }
    return render_template("game.html", info=info, chart_html=chart_html, entries_html=entries_html, xg_html=xg_html)


@app.route("/game/<int:game_id>/canvas")
def game_canvas_view(game_id: int):
    """Gameflow and metrics: the interactive event timeline for one game."""
    if not _game_exists(game_id):
        auto = request.args.get("auto", "0")
        return redirect(url_for("confirm_download", game_id=game_id, auto=auto))
    # The canvas needs the compiled playsequence: the plain one is missing the
    # derived event types the timeline is built around (26 types against 44).
    game = _load_game(game_id, playsequence_source="playsequence_compiled")
    if game is None:
        app.logger.warning(
            "game %s: compiled playsequence unavailable, falling back to the "
            "default source -- the canvas will show fewer event types", game_id)
        game = _load_game(game_id)
    if game is None:
        abort(404, description=f"Game {game_id} could not be loaded.")
    # A whole page of its own, so it is returned as-is rather than rendered
    # into base.html.
    return _build_canvas_html(game)


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


@app.route("/teams")
def teams_page():
    return render_template("teams.html")


@app.route("/teams/<int:team_id>")
def team_detail(team_id: int):
    return render_template("team.html", team_id=team_id)


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    import uuid
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    session_id = (data.get("session_id") or "").strip() or str(uuid.uuid4())

    if not question:
        return jsonify({"error": "No question provided"}), 400

    from hockey.chat.agent import chat as agent_chat
    try:
        result = agent_chat(question, session_id)
    except Exception as e:
        _log_chat(question, None, None, str(e))
        return jsonify({"error": f"Agent error: {e}"}), 500

    _log_chat(question, result.get("sql"), result.get("row_count"), None)
    return jsonify({
        "answer": result["answer"],
        "sql": result.get("sql"),
        "row_count": result.get("row_count"),
        "session_id": session_id,
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
