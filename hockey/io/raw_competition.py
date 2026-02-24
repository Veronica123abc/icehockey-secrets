from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from hockey.model.competition import Season, Stage


@dataclass
class RawCompetition:
    """
    Lazy, cached access to the 5 JSON files for a game.

    Responsibilities:
      - know where files live
      - load JSON on demand
      - cache results
    """
    id: int
    root_dir: Path  # points to directory that contains folders per game_id, or directly files (see _path_for)
    data: dict = field(default_factory=dict)
    #_cache: dict[int, Any] = field(default_factory=dict, init=False, repr=False)

    def _path_for(self) -> Path:
        # Assumes files are at: root_dir/<game_id>/<stem>.json
        # Adjust here if your layout differs.
        return self.root_dir / "leagues" / str(self.id) / "competitions.json" #f"{stem}.json"

    def _load(self) -> Any:
        path = self._path_for()
        with path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)
        return self.data

    @property
    def info(self) -> dict:
        if len(list(self.data.keys())) == 0:
            self._load()
        return self.data



            # @property
    # def seasons(self) -> list:
    #     return self._load("game-info")

