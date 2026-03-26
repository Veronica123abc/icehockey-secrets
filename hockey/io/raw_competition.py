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

    def _path_for_games(self, season:str, stage:str) -> Path:
        return self.root_dir / "leagues" / str(self.id) / season / stage / "games.json"

    def _load(self) -> Any:
        path = self._path_for()
        with path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)
        return self.data

    def _load_games(self, season:str, stage:str) -> list[int]:
        path = self._path_for_games(season, stage)
        game_ids = []
        try:
            with path.open("r", encoding="utf-8") as f:
                games = json.load(f)
                game_ids = [int(game["id"]) for game in games["games"]]
        except FileNotFoundError:f"Could not open {path}!"

        return game_ids

    def load(self):
        self._load()

    @property
    def info(self) -> dict:
        if len(list(self.data.keys())) == 0:
            self._load()
        return self.data

    def game_ids(self, seasons: list[str]=[], stages:list[str]=[]) -> list[int]:
        if stages == []:
            stages = ["regular", "playoffs", "preseason"]
        elif not isinstance(stages, list):
            stages = [stages]
        if seasons == []:
            seasons = [season["name"] for season in self.data["seasons"]]
        elif not isinstance(seasons, list):
            seasons = [seasons]
        else:
            seasons = [season["name"] for season in self.data["seasons"] if season["name"] in seasons]
        game_ids = []
        for season in seasons:
            for stage in stages:
                game_ids += self._load_games(season, stage)
        return game_ids

            # @property
    # def seasons(self) -> list:
    #     return self._load("game-info")

