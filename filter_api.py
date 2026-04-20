"""
Filter API endpoints for cascading game selection.

Provides: /api/leagues, /api/leagues/<id>/seasons,
          /api/leagues/<id>/seasons/<s>/stages,
          /api/leagues/<id>/seasons/<s>/stages/<st>/games
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify

filter_bp = Blueprint("filter", __name__)

_teams_cache: dict[str, str] | None = None
_leagues_cache: list[dict] | None = None
_STAGE_ORDER = {"preseason": 0, "regular": 1, "playoffs": 2}

_MANIFEST_PATH = Path(__file__).resolve().parent / "hockey" / "manifests" / "games.json"


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
    root = _data_root()
    if root is None:
        _teams_cache = {}
        return _teams_cache
    try:
        with (root / "teams.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        teams_list = _extract_list(data)
        _teams_cache = {
            str(t["id"]): t.get("displayName", t.get("name", str(t["id"])))
            for t in teams_list
        }
    except Exception:
        _teams_cache = {}
    return _teams_cache


def _load_leagues() -> list[dict]:
    global _leagues_cache
    if _leagues_cache is not None:
        return _leagues_cache
    root = _data_root()
    if root is None:
        _leagues_cache = []
        return _leagues_cache
    try:
        with (root / "leagues" / "leagues.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        _leagues_cache = _extract_list(data)
    except Exception:
        _leagues_cache = []
    return _leagues_cache


@filter_bp.route("/api/manifest/games")
def api_manifest_games():
    try:
        with _MANIFEST_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return jsonify({"games": []})
    game_list = _extract_list(raw)
    teams = _load_teams()
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
            "home_team_name": teams.get(home_id, "Team " + home_id),
            "away_team_name": teams.get(away_id, "Team " + away_id),
            "home_score": home_score,
            "away_score": away_score,
        })
    return jsonify({"games": result})


@filter_bp.route("/api/leagues")
def api_leagues():
    return jsonify({"leagues": _load_leagues()})


@filter_bp.route("/api/leagues/<league_id>/seasons")
def api_seasons(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"seasons": []})
    root = _data_root()
    if root is None:
        return jsonify({"seasons": []})
    try:
        entries = os.listdir(str(root / "leagues" / league_id))
        seasons = sorted(
            [e for e in entries if not e.startswith(".") and "." not in e],
            reverse=True,
        )
    except OSError:
        seasons = []
    return jsonify({"seasons": seasons})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/stages")
def api_stages(league_id: str, season: str):
    if not (_is_safe_segment(league_id) and _is_safe_segment(season)):
        return jsonify({"stages": []})
    root = _data_root()
    if root is None:
        return jsonify({"stages": []})
    try:
        entries = os.listdir(str(root / "leagues" / league_id / season))
        stages = [e for e in entries if not e.startswith(".") and "." not in e]
        stages.sort(key=lambda s: _STAGE_ORDER.get(s.lower(), 99))
    except OSError:
        stages = []
    return jsonify({"stages": stages})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/stages/<stage>/games")
def api_stage_games(league_id: str, season: str, stage: str):
    if not all(_is_safe_segment(s) for s in (league_id, season, stage)):
        return jsonify({"games": []})
    root = _data_root()
    if root is None:
        return jsonify({"games": []})
    games_path = root / "leagues" / league_id / season / stage / "games.json"
    try:
        with games_path.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception:
        return jsonify({"games": []})

    game_list = _extract_list(raw_data)
    teams = _load_teams()
    result = []
    for g in game_list:
        home_id = str(_get(g, "home_team_id", "homeTeamId"))
        away_id = str(_get(g, "away_team_id", "awayTeamId"))
        result.append({
            "id": _get(g, "id", "game_id", "gameId"),
            "date": _get(g, "date", "gameDate", "game_date"),
            "home_team_name": teams.get(home_id, "Team " + home_id),
            "away_team_name": teams.get(away_id, "Team " + away_id),
            "home_score": _get(g, "home_score", "homeScore", default=None),
            "away_score": _get(g, "away_score", "awayScore", default=None),
        })
    return jsonify({"games": result})
