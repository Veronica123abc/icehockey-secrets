"""
Filter API endpoints for cascading game selection.

Provides: /api/leagues, /api/leagues/<id>/seasons,
          /api/leagues/<id>/seasons/<s>/stages,
          /api/leagues/<id>/seasons/<s>/stages/<st>/games,
          /api/leagues/<id>/games/recent
          POST /admin/refresh-manifests  (requires X-Admin-Secret header)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

filter_bp = Blueprint("filter", __name__)

_teams_cache: dict[str, str] | None = None
_teams_full_cache: list[dict] | None = None
_leagues_cache: list[dict] | None = None
_competition_cache: dict[str, dict] = {}
_games_cache: dict[str, list] = {}  # keyed by "league_id/season"
_STAGE_ORDER = {"preseason": 0, "regular": 1, "playoffs": 2}


def _data_root() -> Path | None:
    d = os.getenv("DATA_ROOT_DIR", "")
    if not d:
        return None
    p = Path(d).expanduser()
    if p.exists() and p.is_dir():
        return p
    return None


_REPO_MANIFEST_DIR = Path(__file__).resolve().parent / "hockey" / "manifests"


def _manifest_dir() -> Path:
    """Per-league trees (competitions, games). Lives under DATA_ROOT_DIR/leagues/."""
    root = _data_root()
    if root:
        return root / "leagues"
    return _REPO_MANIFEST_DIR


def _global_manifest_file(filename: str) -> Path:
    """Global lookups (teams.json, leagues.json). Lives at DATA_ROOT_DIR root."""
    root = _data_root()
    if root:
        p = root / filename
        if p.exists():
            return p
    return _REPO_MANIFEST_DIR / filename


_MANIFEST_DIR = _manifest_dir()


def _is_safe_segment(s: str) -> bool:
    return bool(s) and ".." not in s and "/" not in s and "\\" not in s


def _get(obj: dict, *keys, default=""):
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


def _extract_list(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def _load_teams_full() -> list[dict]:
    global _teams_full_cache
    if _teams_full_cache is not None:
        return _teams_full_cache
    try:
        with _global_manifest_file("teams.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        _teams_full_cache = _extract_list(data)
    except Exception:
        _teams_full_cache = []
    return _teams_full_cache


def _load_teams() -> dict[str, str]:
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache
    _teams_cache = {
        str(t["id"]): t.get("displayName", t.get("name", str(t["id"])))
        for t in _load_teams_full()
    }
    return _teams_cache


def _load_competition(league_id: str) -> dict | None:
    if league_id in _competition_cache:
        return _competition_cache[league_id]
    path = _MANIFEST_DIR / league_id / "competitions.json"
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _competition_cache[league_id] = data
        return data
    except Exception:
        return None


def _load_leagues() -> list[dict]:
    global _leagues_cache
    if _leagues_cache is not None:
        return _leagues_cache
    try:
        with _global_manifest_file("leagues.json").open("r", encoding="utf-8") as f:
            _leagues_cache = json.load(f)
    except Exception:
        _leagues_cache = []
    return _leagues_cache


def _get_games(league_id: str, season: str) -> list:
    key = f"{league_id}/{season}"
    if key not in _games_cache:
        games_path = _MANIFEST_DIR / league_id / season / "games.json"
        try:
            with games_path.open("r", encoding="utf-8") as f:
                _games_cache[key] = _extract_list(json.load(f))
        except Exception:
            _games_cache[key] = []
    return _games_cache[key]


def _clear_caches() -> None:
    global _teams_cache, _teams_full_cache, _leagues_cache, _competition_cache, _games_cache
    _teams_cache = None
    _teams_full_cache = None
    _leagues_cache = None
    _competition_cache = {}
    _games_cache = {}


def _warm_caches() -> None:
    """Eagerly load all manifests into memory at startup."""
    _load_teams_full()
    _load_teams()
    _load_leagues()
    manifest_dir = _manifest_dir()
    if not manifest_dir.exists():
        return
    for league_dir in sorted(manifest_dir.iterdir()):
        if not league_dir.is_dir() or not league_dir.name.isdigit():
            continue
        comp = _load_competition(league_dir.name)
        if comp:
            for season in comp.get("seasons", []):
                _get_games(league_dir.name, season["name"])


def _format_games(game_list: list, teams: dict) -> list[dict]:
    result = []
    for g in game_list:
        home_id = str(_get(g, "home_team_id", "homeTeamId"))
        away_id = str(_get(g, "away_team_id", "awayTeamId"))
        score = g.get("score", {})
        home_score = score.get(home_id) if isinstance(score, dict) else None
        away_score = score.get(away_id) if isinstance(score, dict) else None
        result.append({
            "id": _get(g, "id", "game_id", "gameId"),
            "date": _get(g, "date", "gameDate", "game_date"),
            "stage": g.get("stage", ""),
            "status": g.get("event_status", ""),
            "home_team_name": teams.get(home_id, "Team " + home_id),
            "away_team_name": teams.get(away_id, "Team " + away_id),
            "home_score": home_score,
            "away_score": away_score,
        })
    return result


@filter_bp.route("/api/leagues")
def api_leagues():
    return jsonify({"leagues": _load_leagues()})


@filter_bp.route("/api/leagues/<league_id>/seasons")
def api_seasons(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"seasons": []})
    comp = _load_competition(league_id)
    if not comp:
        return jsonify({"seasons": []})
    seasons = [s["name"] for s in comp.get("seasons", [])]
    return jsonify({"seasons": seasons})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/stages")
def api_stages(league_id: str, season: str):
    if not (_is_safe_segment(league_id) and _is_safe_segment(season)):
        return jsonify({"stages": []})
    comp = _load_competition(league_id)
    if not comp:
        return jsonify({"stages": []})
    season_data = next((s for s in comp.get("seasons", []) if s["name"] == season), None)
    if not season_data:
        return jsonify({"stages": []})
    stages = sorted(
        [st["name"] for st in season_data.get("stages", [])],
        key=lambda s: _STAGE_ORDER.get(s.lower(), 99),
    )
    return jsonify({"stages": stages})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/stages/<stage>/games")
def api_stage_games(league_id: str, season: str, stage: str):
    if not all(_is_safe_segment(s) for s in (league_id, season, stage)):
        return jsonify({"games": []})
    all_games = _get_games(league_id, season)
    game_list = [g for g in all_games if g.get("stage", "").lower() == stage.lower()]
    return jsonify({"games": _format_games(game_list, _load_teams())})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/games")
def api_season_games(league_id: str, season: str):
    """Games for a season, filling from playoffs → regular → preseason."""
    if not (_is_safe_segment(league_id) and _is_safe_segment(season)):
        return jsonify({"games": []})
    limit_param = request.args.get("limit")
    try:
        limit = min(int(limit_param), 2000) if limit_param else None
    except (ValueError, TypeError):
        limit = None

    comp = _load_competition(league_id)
    if not comp:
        return jsonify({"games": []})
    season_data = next((s for s in comp.get("seasons", []) if s["name"] == season), None)
    if not season_data:
        return jsonify({"games": []})

    stage_priority = ["playoffs", "regular", "preseason"]
    all_stage_names = [st["name"] for st in season_data.get("stages", [])]
    ordered_stages = sorted(
        all_stage_names,
        key=lambda s: stage_priority.index(s.lower()) if s.lower() in stage_priority else 99,
    )

    all_games = _get_games(league_id, season)
    teams = _load_teams()
    result = []
    for stage in ordered_stages:
        game_list = sorted(
            [g for g in all_games if g.get("stage", "").lower() == stage.lower()],
            key=lambda g: g.get("date", ""),
            reverse=True,
        )
        result.extend(_format_games(game_list, teams))

    if limit is not None:
        result = result[:limit]
    return jsonify({"games": result})


@filter_bp.route("/api/leagues/<league_id>/games/recent")
def api_recent_games(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"games": []})
    try:
        limit = min(int(request.args.get("limit", 30)), 100)
    except (ValueError, TypeError):
        limit = 30
    comp = _load_competition(league_id)
    if not comp or not comp.get("seasons"):
        return jsonify({"games": []})
    most_recent_season = comp["seasons"][0]["name"]
    game_list = sorted(
        _get_games(league_id, most_recent_season),
        key=lambda g: g.get("date", ""),
        reverse=True,
    )
    return jsonify({
        "games": _format_games(game_list[:limit], _load_teams()),
        "season": most_recent_season,
    })


@filter_bp.route("/api/leagues/<league_id>/teams")
def api_league_teams(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"teams": []})

    comp = _load_competition(league_id)
    if not comp:
        return jsonify({"teams": [], "season": None})

    # Walk seasons newest-first; stop at the first with >= 20 finished games.
    chosen_season = None
    chosen_games = []
    for season in comp.get("seasons", []):
        games = _get_games(league_id, season["name"])
        finished = [g for g in games if g.get("event_status") == "over"]
        if len(finished) >= 20:
            chosen_season = season["name"]
            chosen_games = games
            break

    if chosen_season is None:
        return jsonify({"teams": [], "season": None})

    team_ids = {
        str(g["home_team_id"]) for g in chosen_games if "home_team_id" in g
    } | {
        str(g["away_team_id"]) for g in chosen_games if "away_team_id" in g
    }

    teams_by_id = {str(t["id"]): t for t in _load_teams_full()}
    teams = sorted(
        [
            {
                "id": t["id"],
                "name": t.get("displayName", t.get("name", "")),
                "shorthand": t.get("shorthand", ""),
                "location": t.get("location", ""),
            }
            for tid in team_ids
            if (t := teams_by_id.get(tid)) is not None
        ],
        key=lambda t: t["name"],
    )
    return jsonify({"teams": teams, "season": chosen_season})


@filter_bp.route("/api/teams/<team_id>")
def api_team(team_id: str):
    if not _is_safe_segment(team_id):
        return jsonify({"error": "invalid"}), 400
    team = next((t for t in _load_teams_full() if str(t.get("id", "")) == team_id), None)
    if team is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": team["id"],
        "name": team.get("displayName", team.get("name", "")),
        "shorthand": team.get("shorthand", ""),
        "location": team.get("location", ""),
        "leagueId": team.get("leagueId", ""),
    })


@filter_bp.route("/admin/refresh-manifests", methods=["POST"])
def refresh_manifests():
    secret = os.getenv("ADMIN_SECRET", "")
    if not secret or request.headers.get("X-Admin-Secret") != secret:
        return jsonify({"error": "unauthorized"}), 401
    _clear_caches()
    _warm_caches()
    return jsonify({"ok": True})


# Load all manifests into memory at startup so requests are served from cache.
# On Azure, DATA_ROOT_DIR points to a network share — reading happens once here,
# never on individual requests.
_warm_caches()
