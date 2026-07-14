from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class RawGame:
    """
    Lazy, cached access to the 5 JSON files for a game.

    Responsibilities:
      - know where files live
      - load JSON on demand
      - cache results
    """
    game_id: int
    root_dir: Path  # points to directory that contains folders per game_id, or directly files (see _path_for)
    auto_download: bool = False  # prompt and download from Sportlogiq API if files are missing
    playsequence_source: str = "playsequence"  # stem of the playsequence file: "playsequence" or "playsequence_compiled"
    _cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def _path_for(self, stem: str) -> Path:
        return self.root_dir / str(self.game_id) / f"{stem}.json"

    def _load(self, stem: str) -> Any:
        if stem not in self._cache:
            path = self._path_for(stem)
            try:
                with path.open("r", encoding="utf-8") as f:
                    self._cache[stem] = json.load(f)
            except FileNotFoundError:
                if not self.auto_download:
                    raise
                from hockey.data_collection.sportlogiq_api import prompt_and_download_game
                downloaded = prompt_and_download_game(self.game_id, self.root_dir)
                if not downloaded:
                    raise
                with path.open("r", encoding="utf-8") as f:
                    self._cache[stem] = json.load(f)
        return self._cache[stem]

    @property
    def game_info(self) -> dict:
        return self._load("game-info")

    @property
    def playsequence(self) -> dict:
        return self._load(self.playsequence_source)

    @property
    def roster(self) -> dict:
        return self._load("roster")

    @property
    def player_toi(self) -> dict:
        return self._load("playerTOI")

    def _full_events_by_key(self) -> dict[tuple[float, str], dict]:
        """
        Lazy index of playsequence.json keyed by (game_time, name).
        Always loads the full (non-compiled) playsequence regardless of playsequence_source.
        Built once and cached; the first event at each key wins if timestamps collide.
        """
        cache_key = "_full_events_by_key"
        if cache_key not in self._cache:
            data = self._load("playsequence")
            idx: dict[tuple[float, str], dict] = {}
            for e in data.get("events", []):
                k = (float(e["game_time"]), str(e.get("name", "")))
                idx.setdefault(k, e)
            self._cache[cache_key] = idx
        return self._cache[cache_key]

    def full_event_field(self, game_time: float, name: str, field: str, default: Any = None) -> Any:
        """
        Return a field from the full playsequence event at (game_time, name).
        The field 'playsection' is not used in playsequence_compiled. To fetch this, the matching event in the
        raw playsequence need to be fetched. This is a temporary hack. game_time is a float, non-unique variable which
        is not suitable to query.
        """
        e = self._full_events_by_key().get((game_time, name))
        return e.get(field, default) if e is not None else default