from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from hockey.model.events import Event
from hockey.model.game_info import GameInfo
from hockey.model.toi import ToIInterval


@dataclass
class Game:
    info: GameInfo
    events: list[Event]
    toi: list[ToIInterval]
    roster_raw: dict  # keep raw for now; you can type it later

    _dfs: dict[str, pd.DataFrame] = field(default_factory=dict, init=False, repr=False)

    @property
    def game_id(self) -> int:
        return self.info.game_id

    def events_df(self) -> pd.DataFrame:
        if "events" not in self._dfs:
            self._dfs["events"] = pd.DataFrame(
                {
                    "game_id": [e.game_id for e in self.events],
                    "t": [e.t for e in self.events],
                    "type": [e.type for e in self.events],
                    "team_id_in_possession": [e.team_id_in_possession for e in self.events],
                    "player_id": [e.player_id for e in self.events],
                }
            )
        return self._dfs["events"]

    def toi_df(self) -> pd.DataFrame:
        if "toi" not in self._dfs:
            self._dfs["toi"] = pd.DataFrame(
                {
                    "game_id": [x.game_id for x in self.toi],
                    "team_id": [x.team_id for x in self.toi],
                    "player_id": [x.player_id for x in self.toi],
                    "start_t": [x.start_t for x in self.toi],
                    "end_t": [x.end_t for x in self.toi],
                }
            )
        return self._dfs["toi"]
