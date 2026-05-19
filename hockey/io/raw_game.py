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
        return self._load("playsequence")

    @property
    def roster(self) -> dict:
        return self._load("roster")

    @property
    def player_toi(self) -> dict:
        return self._load("playerTOI")