from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class Event:
    game_id: int
    t: float                      # game time in seconds
    type: str                     # e.g. "pass", "shot", "whistle", ...
    name: str
    team_id_in_possession: Optional[int]
    team_id: Optional[int]
    player_id: Optional[int]
    team_defencemen_on_ice_refs: Optional[list[int]]
    grade: Optional[str]
    raw: dict                     # keep raw payload for now; you can drop later
    event_id: Optional[int] = None
    base_event_id: Optional[int] = None
    # On-ice rosters at the moment of the event. Only playsequence.json carries
    # these; on the compiled path they are filled in by linking the two files
    # (RawGame.full_event_for). Empty when linking is off or unavailable.
    team_forwards_on_ice_refs: Optional[list[int]] = None
    team_goalie_on_ice_ref: Optional[int] = None
    opposing_team_forwards_on_ice_refs: Optional[list[int]] = None
    opposing_team_defencemen_on_ice_refs: Optional[list[int]] = None
    opposing_team_goalie_on_ice_ref: Optional[int] = None

    @property
    def players_on_ice(self) -> list[int]:
        """Every player on the ice for this event, both teams, goalies included.

        Empty when the event was not linked to playsequence.json -- an empty
        list means "unknown", not "nobody".
        """
        out: list[int] = []
        for refs in (self.team_forwards_on_ice_refs,
                     self.team_defencemen_on_ice_refs,
                     self.opposing_team_forwards_on_ice_refs,
                     self.opposing_team_defencemen_on_ice_refs):
            if refs:
                out.extend(refs)
        for goalie in (self.team_goalie_on_ice_ref,
                       self.opposing_team_goalie_on_ice_ref):
            if goalie is not None:
                out.append(goalie)
        return out

    def get_raw(self, key: str, default: T = None) -> Any | T:
        """
        Safe getter for supplier raw payload.

        - Returns default if raw is missing or not a dict
        - Returns default if key is not present

        Example:
            x = event.get_raw("expected_goals", 0.0)
        """
        raw = self.raw
        if not isinstance(raw, dict):
            return default
        return raw.get(key, default)
