from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Event:
    game_id: int
    t: float                      # game time in seconds
    type: str                     # e.g. "pass", "shot", "whistle", ...
    name: str
    team_id_in_possession: Optional[int]
    player_id: Optional[int]
    team_defencemen_on_ice_refs: Optional[list[int]]
    grade: Optional[str]
    raw: dict                     # keep raw payload for now; you can drop later