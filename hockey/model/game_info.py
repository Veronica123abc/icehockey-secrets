from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class TeamInfo:
    id: int
    location: str
    name: str

    @property
    def display_name(self) -> str:
        # This matches the string used in playsequence (per your description).
        return f"{self.location} {self.name}".strip()


@dataclass(frozen=True, slots=True)
class GameInfo:
    game_id: int
    home_team: TeamInfo
    away_team: TeamInfo
    # Optional metadata -- present on the JSON path, left None by loaders that
    # don't have it (e.g. build_game_from_db). Render defensively.
    date: Optional[str] = None            # ISO date, e.g. "2025-09-13"
    stage: Optional[str] = None           # e.g. "regular", "playoff"
    home_final_score: Optional[int] = None
    away_final_score: Optional[int] = None
    # Add more fields later (venue, season, etc.) as needed.