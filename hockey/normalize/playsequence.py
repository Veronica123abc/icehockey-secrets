from __future__ import annotations

from typing import Optional

from hockey.model.events import Event
from hockey.normalize.team_resolution import TeamResolver


def _maybe_int(x) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def normalize_playsequence(
    *,
    game_id: int,
    raw_playsequence: dict,
    teams: TeamResolver,
) -> list[Event]:
    events = []
    for e in raw_playsequence.get("events", []):
        t = float(e["game_time"])
        event_type = str(e.get("name", "")).strip()

        team_id = teams.team_id_from_string(e.get("team_in_possession"))
        player_id = _maybe_int(e.get("player_reference_id"))

        events.append(
            Event(
                game_id=game_id,
                t=t,
                type=event_type,
                team_id_in_possession=team_id,
                player_id=player_id,
                raw=e,
            )
        )
    return events