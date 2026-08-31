"""
Filter API endpoints for cascading game selection.

Provides: /api/leagues, /api/leagues/<id>/seasons,
          /api/leagues/<id>/seasons/<s>/stages,
          /api/leagues/<id>/seasons/<s>/stages/<st>/games,
          /api/leagues/<id>/games/recent,
          /api/leagues/<id>/teams,
          /api/teams/<team_id>
          POST /admin/refresh-manifests  (requires X-Admin-Secret header)

Backend is selected at startup:
  - FILTER_BACKEND=db       → DbProvider (fail hard if DB unavailable)
  - FILTER_BACKEND=manifest → ManifestProvider
  - (unset)                 → DbProvider if DATABASE_HOST_AZURE is set, else ManifestProvider
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path

from flask import Blueprint, jsonify, request

filter_bp = Blueprint("filter", __name__)
_log = logging.getLogger(__name__)

_STAGE_ORDER = {"preseason": 0, "regular": 1, "playoffs": 2}
_REPO_MANIFEST_DIR = Path(__file__).resolve().parent / "hockey" / "manifests"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _format_games(game_list: list, teams: dict[str, str]) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class FilterProvider(ABC):
    """Common interface for manifest- and DB-backed filter data."""

    @abstractmethod
    def load_leagues(self) -> list[dict]: ...

    @abstractmethod
    def load_teams_full(self) -> list[dict]: ...

    @abstractmethod
    def load_competition(self, league_id: str) -> dict | None: ...

    @abstractmethod
    def get_games(self, league_id: str, season: str) -> list: ...

    def load_teams(self) -> dict[str, str]:
        return {
            str(t["id"]): t.get("displayName", t.get("name", str(t["id"])))
            for t in self.load_teams_full()
        }

    def warm(self) -> None:
        pass

    def clear(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Manifest provider
# ---------------------------------------------------------------------------

class ManifestProvider(FilterProvider):

    def __init__(self) -> None:
        self._leagues_cache: list[dict] | None = None
        self._teams_full_cache: list[dict] | None = None
        self._competition_cache: dict[str, dict] = {}
        self._games_cache: dict[str, list] = {}

    def _data_root(self) -> Path | None:
        d = os.getenv("DATA_ROOT_DIR", "")
        if not d:
            return None
        p = Path(d).expanduser()
        return p if p.exists() and p.is_dir() else None

    def _manifest_dir(self) -> Path:
        # Mirror _global_manifest_file: only prefer the data dir when it really
        # holds manifests, otherwise fall back to the ones bundled in the repo.
        root = self._data_root()
        if root:
            p = root / "leagues"
            if p.is_dir():
                return p
        return _REPO_MANIFEST_DIR

    def _global_manifest_file(self, filename: str) -> Path:
        root = self._data_root()
        if root:
            p = root / filename
            if p.exists():
                return p
        return _REPO_MANIFEST_DIR / filename

    def load_leagues(self) -> list[dict]:
        if self._leagues_cache is None:
            try:
                with self._global_manifest_file("leagues.json").open("r", encoding="utf-8") as f:
                    self._leagues_cache = json.load(f)
            except Exception:
                self._leagues_cache = []
        return self._leagues_cache

    def load_teams_full(self) -> list[dict]:
        if self._teams_full_cache is None:
            try:
                with self._global_manifest_file("teams.json").open("r", encoding="utf-8") as f:
                    data = json.load(f)
                self._teams_full_cache = _extract_list(data)
            except Exception:
                self._teams_full_cache = []
        return self._teams_full_cache

    def load_competition(self, league_id: str) -> dict | None:
        if league_id not in self._competition_cache:
            path = self._manifest_dir() / league_id / "competitions.json"
            try:
                with path.open("r", encoding="utf-8") as f:
                    self._competition_cache[league_id] = json.load(f)
            except Exception:
                return None
        return self._competition_cache.get(league_id)

    def get_games(self, league_id: str, season: str) -> list:
        key = f"{league_id}/{season}"
        if key not in self._games_cache:
            path = self._manifest_dir() / league_id / season / "games.json"
            try:
                with path.open("r", encoding="utf-8") as f:
                    self._games_cache[key] = _extract_list(json.load(f))
            except Exception:
                self._games_cache[key] = []
        return self._games_cache[key]

    def warm(self) -> None:
        self.load_teams_full()
        self.load_leagues()
        mdir = self._manifest_dir()
        if not mdir.exists():
            return
        for league_dir in sorted(mdir.iterdir()):
            if not league_dir.is_dir() or not league_dir.name.isdigit():
                continue
            comp = self.load_competition(league_dir.name)
            if comp:
                for season in comp.get("seasons", []):
                    self.get_games(league_dir.name, season["name"])

    def clear(self) -> None:
        self._leagues_cache = None
        self._teams_full_cache = None
        self._competition_cache = {}
        self._games_cache = {}


# ---------------------------------------------------------------------------
# DB provider
# ---------------------------------------------------------------------------

class DbProvider(FilterProvider):

    def __init__(self) -> None:
        self._leagues_cache: list[dict] | None = None
        self._teams_full_cache: list[dict] | None = None
        self._competition_cache: dict[str, dict] = {}
        self._games_cache: dict[str, list] = {}

    def _db_conn(self):
        import mysql.connector
        return mysql.connector.connect(
            host=os.environ["DATABASE_HOST_AZURE"],
            user=os.environ["DATABASE_USERNAME_AZURE"],
            password=os.environ["DATABASE_PWD_AZURE"],
            database=os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
            auth_plugin="mysql_native_password",
            connect_timeout=10,
        )

    def load_leagues(self) -> list[dict]:
        return self._leagues_cache or []

    def load_teams_full(self) -> list[dict]:
        return self._teams_full_cache or []

    def load_competition(self, league_id: str) -> dict | None:
        return self._competition_cache.get(league_id)

    def get_games(self, league_id: str, season: str) -> list:
        return self._games_cache.get(f"{league_id}/{season}", [])

    def warm(self) -> None:
        conn = self._db_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name FROM league ORDER BY name")
            self._leagues_cache = [
                {"id": str(r[0]), "name": r[1]} for r in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT id, name, display_name, location, shorthand, league_id FROM team"
            )
            self._teams_full_cache = [
                {
                    "id": str(r[0]),
                    "name": r[1] or "",
                    "displayName": r[2] or r[1] or "",
                    "location": r[3] or "",
                    "shorthand": r[4] or "",
                    "leagueId": str(r[5]) if r[5] is not None else "",
                }
                for r in cursor.fetchall()
            ]

            # game.sl_id is kept as the game identifier (links to /game/<sl_id>).
            # Everything else uses internal DB ids — no joins needed.
            cursor.execute(
                """
                SELECT league_id, season, stage, sl_id,
                       DATE(scheduled_time), event_status,
                       home_team_goals, away_team_goals,
                       home_team_id, away_team_id
                FROM game
                """
            )
            games_by_key: dict[str, list] = defaultdict(list)
            comp_data: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

            for l_id, season, stage, g_sl, date, status, hg, ag, h_id, a_id in cursor.fetchall():
                l_key = str(l_id)
                score: dict = {}
                if hg is not None and h_id is not None:
                    score[str(h_id)] = hg
                if ag is not None and a_id is not None:
                    score[str(a_id)] = ag
                games_by_key[f"{l_key}/{season}"].append({
                    "id": str(g_sl) if g_sl is not None else "",
                    "date": str(date) if date else "",
                    "stage": stage or "",
                    "event_status": status or "",
                    "home_team_id": h_id,
                    "away_team_id": a_id,
                    "score": score,
                })
                if stage:
                    comp_data[l_key][season].add(stage)

            self._games_cache = dict(games_by_key)
            self._competition_cache = {
                l_key: {
                    "seasons": [
                        {
                            "name": s,
                            "stages": sorted(
                                [{"name": st} for st in stages],
                                key=lambda x: _STAGE_ORDER.get(x["name"].lower(), 99),
                            ),
                        }
                        for s, stages in sorted(seasons.items(), reverse=True)
                    ]
                }
                for l_key, seasons in comp_data.items()
            }
        finally:
            cursor.close()
            conn.close()

    def clear(self) -> None:
        self._leagues_cache = None
        self._teams_full_cache = None
        self._competition_cache = {}
        self._games_cache = {}


# ---------------------------------------------------------------------------
# Chain provider
# ---------------------------------------------------------------------------

class ChainProvider(FilterProvider):
    """Query providers in order, falling back when one has no data.

    The DB only holds games that have actually been ingested, while the
    bundled manifests carry the full league/season/game catalogue. Chaining
    them means a league absent from the DB still resolves through the
    manifests instead of returning an empty dropdown.
    """

    def __init__(self, providers: list[FilterProvider]) -> None:
        self._providers = list(providers)

    def _union_by_id(self, method: str) -> list[dict]:
        seen: set[str] = set()
        merged: list[dict] = []
        for p in self._providers:
            for item in getattr(p, method)():
                item_id = str(item.get("id", ""))
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    merged.append(item)
        return merged

    def load_leagues(self) -> list[dict]:
        return sorted(
            self._union_by_id("load_leagues"), key=lambda lg: lg.get("name", "")
        )

    def load_teams_full(self) -> list[dict]:
        return self._union_by_id("load_teams_full")

    def load_competition(self, league_id: str) -> dict | None:
        for p in self._providers:
            comp = p.load_competition(league_id)
            if comp and comp.get("seasons"):
                return comp
        return None

    def get_games(self, league_id: str, season: str) -> list:
        for p in self._providers:
            games = p.get_games(league_id, season)
            if games:
                return games
        return []

    def warm(self) -> None:
        for p in self._providers:
            p.warm()

    def clear(self) -> None:
        for p in self._providers:
            p.clear()


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _make_provider() -> FilterProvider:
    backend = os.getenv("FILTER_BACKEND", "").lower()
    use_db = backend == "db" or (not backend and bool(os.getenv("DATABASE_HOST_AZURE")))
    if use_db:
        try:
            db = DbProvider()
            db.warm()
            # ManifestProvider is left cold on purpose: it loads lazily and
            # caches per file, so chaining it costs nothing at startup.
            _log.info("filter_api: using DbProvider with ManifestProvider fallback")
            return ChainProvider([db, ManifestProvider()])
        except Exception as exc:
            if backend == "db":
                raise RuntimeError("FILTER_BACKEND=db but DB warm failed") from exc
            _log.warning("filter_api: DbProvider failed (%s), falling back to ManifestProvider", exc)
    p = ManifestProvider()
    p.warm()
    _log.info("filter_api: using ManifestProvider")
    return p


_provider: FilterProvider = _make_provider()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@filter_bp.route("/api/leagues")
def api_leagues():
    return jsonify({"leagues": _provider.load_leagues()})


@filter_bp.route("/api/leagues/<league_id>/seasons")
def api_seasons(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"seasons": []})
    comp = _provider.load_competition(league_id)
    if not comp:
        return jsonify({"seasons": []})
    return jsonify({"seasons": [s["name"] for s in comp.get("seasons", [])]})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/stages")
def api_stages(league_id: str, season: str):
    if not (_is_safe_segment(league_id) and _is_safe_segment(season)):
        return jsonify({"stages": []})
    comp = _provider.load_competition(league_id)
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
    all_games = _provider.get_games(league_id, season)
    game_list = [g for g in all_games if g.get("stage", "").lower() == stage.lower()]
    return jsonify({"games": _format_games(game_list, _provider.load_teams())})


@filter_bp.route("/api/leagues/<league_id>/seasons/<season>/games")
def api_season_games(league_id: str, season: str):
    if not (_is_safe_segment(league_id) and _is_safe_segment(season)):
        return jsonify({"games": []})
    limit_param = request.args.get("limit")
    try:
        limit = min(int(limit_param), 2000) if limit_param else None
    except (ValueError, TypeError):
        limit = None

    comp = _provider.load_competition(league_id)
    if not comp:
        return jsonify({"games": []})
    season_data = next((s for s in comp.get("seasons", []) if s["name"] == season), None)
    if not season_data:
        return jsonify({"games": []})

    stage_priority = ["playoffs", "regular", "preseason"]
    ordered_stages = sorted(
        [st["name"] for st in season_data.get("stages", [])],
        key=lambda s: stage_priority.index(s.lower()) if s.lower() in stage_priority else 99,
    )
    all_games = _provider.get_games(league_id, season)
    teams = _provider.load_teams()
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
    comp = _provider.load_competition(league_id)
    if not comp or not comp.get("seasons"):
        return jsonify({"games": []})
    most_recent_season = comp["seasons"][0]["name"]
    game_list = sorted(
        _provider.get_games(league_id, most_recent_season),
        key=lambda g: g.get("date", ""),
        reverse=True,
    )
    return jsonify({
        "games": _format_games(game_list[:limit], _provider.load_teams()),
        "season": most_recent_season,
    })


@filter_bp.route("/api/leagues/<league_id>/teams")
def api_league_teams(league_id: str):
    if not _is_safe_segment(league_id):
        return jsonify({"teams": [], "season": None})

    comp = _provider.load_competition(league_id)
    if not comp:
        return jsonify({"teams": [], "season": None})

    season_param = request.args.get("season", "").strip()
    if season_param and _is_safe_segment(season_param):
        chosen_season = season_param
        chosen_games = _provider.get_games(league_id, chosen_season)
    else:
        chosen_season = None
        chosen_games = []
        for season in comp.get("seasons", []):
            games = _provider.get_games(league_id, season["name"])
            if sum(1 for g in games if g.get("event_status") == "over") >= 20:
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
    teams_by_id = {str(t["id"]): t for t in _provider.load_teams_full()}
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
    team = next(
        (t for t in _provider.load_teams_full() if str(t.get("id", "")) == team_id), None
    )
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
    _provider.clear()
    _provider.warm()
    return jsonify({"ok": True, "backend": type(_provider).__name__})
