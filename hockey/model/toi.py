from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class ToIInterval:
    game_id: int
    team_id: Optional[int]     # optional until fully resolved
    player_id: int
    start_t: float
    end_t: Optional[float]     # None if no OUT seen