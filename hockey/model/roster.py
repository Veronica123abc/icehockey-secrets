from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Player:
    player_id: int
    team_id: Optional[int]  # if you can resolve it; otherwise keep None initially
    first_name: Optional[str]
    last_name: Optional[str]
    position: Optional[str]  # "G", "D", "F", etc.
    shoots: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Roster:
    game_id: int
    players: dict[int, Player]  # key: player_id
