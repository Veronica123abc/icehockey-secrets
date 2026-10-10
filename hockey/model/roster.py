from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: The ``position`` value marking a goalie. One literal, because "is this
#: player a skater" is asked in four layers -- the span policy in
#: ``model/toi.py``, the manpower timeline in ``metrics/on_ice_spans.py``, the
#: shift query in ``hockey/db`` -- and each used to spell it itself.
GOALIE = "G"


@dataclass(frozen=True, slots=True)
class Player:
    player_id: int
    team_id: Optional[int]  # if you can resolve it; otherwise keep None initially
    first_name: Optional[str]
    last_name: Optional[str]
    position: Optional[str]  # "G", "D", "F", etc.
    shoots: Optional[str] = None
    jersey_number: Optional[int] = None


@dataclass(frozen=True, slots=True)
class Roster:
    game_id: int
    players: dict[int, Player]  # key: player_id
