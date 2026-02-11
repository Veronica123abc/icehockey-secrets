from __future__ import annotations

from dataclasses import dataclass


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
    # Add more fields later (date, venue, score, season, etc.) as needed.