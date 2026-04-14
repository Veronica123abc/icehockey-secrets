from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from hockey.model.events import Event
from hockey.model.game_info import GameInfo
from hockey.model.toi import ToIInterval
from hockey.model.roster import Roster
from hockey.derive.current_shift import current_shift_toi
from hockey.derive.current_shift_series import current_shift_toi_series, current_shift_toi_series_old

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

    def events_supplier_df(self) -> pd.DataFrame:
        """
        Supplier event payload only.
        Each key in the raw dict becomes a column.
        """
        if "events_supplier" not in self._dfs:
            self._dfs["events_supplier"] = pd.DataFrame([e.raw for e in self.events])

        return self._dfs["events_supplier"]

    def events_enriched_df(self) -> pd.DataFrame:
        """
        Supplier event payload plus normalized convenience columns from Event.
        """
        if "events_enriched" not in self._dfs:
            df = self.events_supplier_df().copy()
            df.insert(0, "game_id", [e.game_id for e in self.events])
            df.insert(1, "t", [e.t for e in self.events])
            df.insert(2, "team_id_in_possession", [e.team_id_in_possession for e in self.events])
            df.insert(3, "team_id", [e.team_id for e in self.events])
            df.insert(4, "player_id", [e.player_id for e in self.events])

            self._dfs["events_enriched"] = df

        return self._dfs["events_enriched"]

    def events_raw_df(self) -> pd.DataFrame:
        """
        Backwards-compatible alias for the enriched event dataframe.
        """
        return self.events_enriched_df()

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

    def shift_toi_series_old(self, *, start_time: int = 0, end_time: int = 3600, include_goalies: bool = False, reset_on_whistle: bool = False):
        return current_shift_toi_series_old(self, start_time=start_time, end_time=end_time, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)

    def shift_toi_series(self, queries):
        return current_shift_toi_series(self, query_times=queries)#, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)

    # def shift_toi_series_2(self, *, start_time: int = 0, end_time: int = 3600, include_goalies: bool = False, reset_on_whistle: bool = False):
    #     return current_shift_toi_series_2(self, start_time=start_time, end_time=end_time, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)
    #
    # def shift_toi_series_3(self, *, start_time: int = 0, end_time: int = 3600, include_goalies: bool = False, reset_on_whistle: bool = False):
    #     return current_shift_toi_series_3(self, start_time=start_time, end_time=end_time, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)
    #
    # def shift_toi_series_3(self, *, start_time: int = 0, end_time: int = 3600, include_goalies: bool = False, reset_on_whistle: bool = False):
    #     return current_shift_toi_series_3(self, start_time=start_time, end_time=end_time, include_goalies=include_goalies, reset_on_whistle=reset_on_whistle)


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