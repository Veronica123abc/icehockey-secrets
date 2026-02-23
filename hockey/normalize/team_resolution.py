from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hockey.model.game_info import GameInfo


@dataclass(frozen=True)
class TeamResolver:
    """
    Maps supplier team display strings -> global team ids (from game-info).
    """
    home_display: str
    away_display: str
    home_id: int
    away_id: int

    @classmethod
    def from_game_info(cls, info: GameInfo) -> "TeamResolver":
        return cls(
            home_display=info.home_team.display_name,
            away_display=info.away_team.display_name,
            home_id=info.home_team.id,
            away_id=info.away_team.id,
        )

    def team_id_from_string(self, s: Optional[str]) -> Optional[int]:

        if s is None:
            return None
        s = str(s).strip()
        if not s or s == "None":
            return None
        if s == self.home_display:
            return self.home_id
        if s == self.away_display:
            return self.away_id

        #Big time hack to handle Utahs name-change during 2025
        if self.home_display[0:4] == "Utah":
            return self.home_id
        if self.away_display[0:4] == "Utah":
            return self.away_id
        raise ValueError(
            f"Unknown team string: {s!r}. Expected {self.home_display!r} or {self.away_display!r}."
        )

    # Backwards-compatible name (if you already used it elsewhere)
    def team_id_from_possession_string(self, s: Optional[str]) -> Optional[int]:
        return self.team_id_from_string(s)