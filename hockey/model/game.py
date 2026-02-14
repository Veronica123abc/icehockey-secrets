from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from hockey.model.events import Event
from hockey.model.game_info import GameInfo
from hockey.model.toi import ToIInterval
from hockey.model.roster import Roster
from hockey.derive.current_shift import current_shift_toi


@dataclass
class Game:
    info: GameInfo
    events: list[Event]
    toi: list[ToIInterval]
    roster: Roster

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

    def events_raw_df(self) -> pd.DataFrame:
        """
        Returns the *raw supplier event dicts* as a DataFrame.
        Each key in the raw dict becomes a column.

        Notes:
        - Nested structures (lists/dicts) will appear as object dtype columns.
        - We also add a few normalized columns (game_id, t, name, type, etc.) for convenience.
        """
        if "events_raw" not in self._dfs:
            df = pd.DataFrame([e.raw for e in self.events])

            # Add a few normalized fields up front to simplify filtering/joins
            df.insert(0, "game_id", [e.game_id for e in self.events])
            df.insert(1, "t", [e.t for e in self.events])
            df.insert(2, "team_id_in_possession", [e.team_id_in_possession for e in self.events])
            df.insert(3, "player_id", [e.player_id for e in self.events])

            self._dfs["events_raw"] = df

        return self._dfs["events_raw"]

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

    def current_shift_toi(self, game_time: float, *, include_goalies: bool = False, reset_on_whistle: bool = True) -> dict:

        return current_shift_toi(self, game_time, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)

    # def current_shift_toi(
    #         self,
    #         game_time: float,
    #         *,
    #         include_goalies: bool = False,
    #         reset_on_whistle: bool = True,
    # ) -> dict:
    #     return current_shift_toi(
    #         self,
    #         game_time,
    #         include_goalies=include_goalies,
    #         reset_on_whistle=reset_on_whistle,
    #     )