from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from hockey.io.raw_game import RawGame

_ALL_GAME_FILES = ("game-info", "playsequence", "roster", "playerTOI", "playsequence_compiled", "shifts")
_REQUIRED_GAME_FILES = frozenset({"game-info", "playsequence", "roster", "playerTOI"})


@dataclass(frozen=True)
class GameFileSet:
    game_id: int
    present: frozenset[str]
    root_dir: Path

    @property
    def is_loadable(self) -> bool:
        """All files required by build_game are present."""
        return _REQUIRED_GAME_FILES <= self.present

    def is_complete(self, min_bytes: int = 1000) -> bool:
        """All required files are present and above min_bytes in size."""
        if not self.is_loadable:
            return False
        game_dir = self.root_dir / str(self.game_id)
        return all(
            (game_dir / f"{f}.json").stat().st_size >= min_bytes
            for f in _REQUIRED_GAME_FILES
        )

    def missing(self) -> list[str]:
        return [f for f in _ALL_GAME_FILES if f not in self.present]


class DataCatalog:
    def __init__(self, data_root: Path | str):
        self._root = Path(data_root).expanduser()
        self._competitions: dict = {}

    # ── Game data ────────────────────────────────────────────────────────────

    def raw_game(self, game_id: int) -> RawGame:
        return RawGame(game_id=game_id, root_dir=self._root)

    def game_fileset(self, game_id: int) -> GameFileSet:
        game_dir = self._root / str(game_id)
        present = frozenset(
            stem for stem in _ALL_GAME_FILES
            if (game_dir / f"{stem}.json").exists()
        )
        return GameFileSet(game_id=game_id, present=present, root_dir=self._root)

    def local_game_ids(self) -> list[int]:
        """All game IDs that have at least game-info.json on disk."""
        ids = []
        try:
            with os.scandir(str(self._root)) as it:
                for entry in it:
                    if entry.is_dir() and entry.name.isdigit():
                        if (self._root / entry.name / "game-info.json").exists():
                            ids.append(int(entry.name))
        except OSError:
            pass
        return sorted(ids)

    def complete_game_ids(self, check_filesize: bool = False, min_bytes: int = 1000) -> list[int]:
        """Game IDs that have all files required by build_game."""
        result = []
        for gid in self.local_game_ids():
            fs = self.game_fileset(gid)
            ok = fs.is_complete(min_bytes) if check_filesize else fs.is_loadable
            if ok:
                result.append(gid)
        return result

    # ── League / schedule ────────────────────────────────────────────────────

    def raw_competition(self, league_id: int):
        from hockey.io.raw_competition import RawCompetition
        if league_id not in self._competitions:
            self._competitions[league_id] = RawCompetition(id=league_id, root_dir=self._root)
        return self._competitions[league_id]

    def scheduled_game_ids(
        self,
        league_id: int,
        season: str,
        stages: list[str] | None = None,
        event_status: str | None = None,
    ) -> list[int]:
        """Game IDs from the season schedule, optionally filtered by stage and/or event_status."""
        season_path = self._root / "leagues" / str(league_id) / season / "games.json"
        try:
            with season_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            games = data.get("games", data) if isinstance(data, dict) else data
            if stages:
                stages_lower = {s.lower() for s in stages}
                games = [g for g in games if g.get("stage", "").lower() in stages_lower]
            if event_status is not None:
                games = [g for g in games if g.get("event_status") == event_status]
            return sorted(int(g["id"]) for g in games)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No schedule found at {season_path}. "
                f"Run fetch_schedules.py to download it first."
            )

    def season_schedule(self, league_id: int, season: str) -> dict:
        """Raw schedule JSON for a season — suitable for ingest_game()."""
        path = self._root / "leagues" / str(league_id) / season / "games.json"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def season_players(self, league_id: int, season: str) -> list[dict]:
        """Player list for a season — suitable for ingest_players()."""
        path = self._root / "leagues" / str(league_id) / season / "players.json"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("players", data) if isinstance(data, dict) else data

    def leagues(self) -> list[dict]:
        """League list — suitable for ingest_leagues()."""
        path = self._root / "leagues" / "leagues.json"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("leagues", [])

    def teams(self) -> list[dict]:
        """Team list — suitable for ingest_teams()."""
        path = self._root / "teams.json"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("teams", data) if isinstance(data, dict) else data

    def season_teams(self, league_id: int, season: str) -> list[dict]:
        """Team list — suitable for ingest_teams()."""
        path = self._root / "teams.json"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("teams", data) if isinstance(data, dict) else data

    # ── Writes ───────────────────────────────────────────────────────────────

    def save_competition(self, league_id: int, data: dict) -> None:
        path = self._root / "leagues" / str(league_id) / "competitions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def save_season_schedule(
        self, league_id: int, season: str, data: dict, stage: str | None = None
    ) -> None:
        base = self._root / "leagues" / str(league_id) / season
        path = (base / stage / "games.json") if stage else (base / "games.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def save_season_players(self, league_id: int, season: str, data: dict) -> None:
        path = self._root / "leagues" / str(league_id) / season / "players.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def save_all_competitions(self, data: dict) -> None:
        path = self._root / "all_competitions.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, sort_keys=True)

    # ── League enumeration ───────────────────────────────────────────────────

    def known_league_ids(self) -> list[int]:
        """League IDs that have a competitions.json in leagues/."""
        leagues_dir = self._root / "leagues"
        ids = []
        try:
            with os.scandir(str(leagues_dir)) as it:
                for entry in it:
                    if entry.is_dir() and entry.name.isdigit():
                        if (leagues_dir / entry.name / "competitions.json").exists():
                            ids.append(int(entry.name))
        except OSError:
            pass
        return sorted(ids)

    # ── Completeness ─────────────────────────────────────────────────────────

    def missing_game_ids(
        self,
        league_id: int,
        season: str,
        event_status: str | None = None,
        check_filesize: bool = False,
        min_bytes: int = 1000,
    ) -> list[int]:
        """Scheduled game IDs that are not fully present locally."""
        scheduled = set(self.scheduled_game_ids(league_id, season, event_status=event_status))
        complete = set(self.complete_game_ids(check_filesize=check_filesize, min_bytes=min_bytes))
        return sorted(scheduled - complete)

    def completeness_report(self, league_id: int, season: str) -> list[GameFileSet]:
        """FileSet for every scheduled game in the season."""
        return [self.game_fileset(gid) for gid in self.scheduled_game_ids(league_id, season)]
