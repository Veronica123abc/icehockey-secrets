"""
Filter API endpoints for cascading game selection.

Provides: /api/leagues, /api/leagues/<id>/seasons,
          /api/leagues/<id>/seasons/<s>/stages,
          /api/leagues/<id>/seasons/<s>/stages/<st>/games,
          /api/leagues/<id>/games/recent
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

filter_bp = Blueprint("filter", __name__)

_teams_cache: dict[str, str] | None = None
_leagues_cache: list[dict] | None = None
_competition_cache: dict[str, dict] = {}
_STAGE_ORDER = {"preseason": 0, "regular": 1, "playoffs": 2}

_MANIFEST_DIR = Path(__file__).resolve().parent / "hockey" / "manifests"


def _data_root() -> Path | None:
    d = os.getenv("DATA_ROOT_DIR", "")
    if not d:
        return None
    p = Path(d).expanduser()
    if p.exists() and p.is_dir():
        return p
    return None


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


def _load_teams() -> dict[str, str]:
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache
    try:
        with (_MANIFEST_DIR / "teams.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        teams_list = _extract_list(data)
        _teams_cache = {
            str(t["id"]): t.get("displayName", t.get("name", str(t["id"])))
            for t in teams_list
        }
    except Exception:
        _teams_cache = {}
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
        with (_MANIFEST_DIR / "leagues.json").open("r", encoding="utf-8") as f:
            _leagues_cache = json.load(f)
    except Exception:
        _leagues_cache = []
    return _leagues_cache


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
    season_path = _MANIFEST_DIR / league_id / season / "games.json"
    try:
        with season_path.open("r", encoding="utf-8") as f:
            game_list = [g for g in _extract_list(json.load(f)) if g.get("stage", "").lower() == stage.lower()]
    except Exception:
        return jsonify({"games": []})
    teams = _load_teams()
    return jsonify({"games": _format_games(game_list, teams)})


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

    teams = _load_teams()
    result = []
    season_path = _MANIFEST_DIR / league_id / season / "games.json"

    try:
        with season_path.open("r", encoding="utf-8") as f:
            all_games = _extract_list(json.load(f))
    except Exception:
        return jsonify({"games": []})

    for stage in ordered_stages:
        game_list = [g for g in all_games if g.get("stage", "").lower() == stage.lower()]
        game_list_sorted = sorted(game_list, key=lambda g: g.get("date", ""), reverse=True)
        result.extend(_format_games(game_list_sorted, teams))

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
    games_path = _MANIFEST_DIR / league_id / most_recent_season / "games.json"
    try:
        with games_path.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception:
        return jsonify({"games": []})
    game_list = _extract_list(raw_data)
    game_list_sorted = sorted(game_list, key=lambda g: g.get("date", ""), reverse=True)
    teams = _load_teams()
    return jsonify({
        "games": _format_games(game_list_sorted[:limit], teams),
        "season": most_recent_season,
    })


# Warm up caches at import time so the first request is fast
_load_teams()
_load_leagues()
