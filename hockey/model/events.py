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