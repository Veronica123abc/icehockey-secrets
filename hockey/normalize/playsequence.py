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

def _int_list(xs):
    if not xs:
        return []
    out = []
    for x in xs:
        v = _maybe_int(x)
        if v is not None:
            out.append(v)
    return out


def normalize_playsequence(
    *,
    game_id: int,
    raw_playsequence: dict,
    teams: TeamResolver,
) -> list[Event]:
    events = []
    for e in raw_playsequence.get("events", []):
        t = float(e["game_time"])
        type = str(e.get("type", "")).strip()
        name = str(e.get("name", "")).strip()
        team_id = teams.team_id_from_string(e.get("team_in_possession"))
        player_id = _maybe_int(e.get("player_reference_id"))
        grade = e.get("expected_goals_all_shots_grade")
        team_defencemen_on_ice_refs = _int_list(e.get("team_defencemen_on_ice_refs"))
        events.append(
            Event(
                game_id=game_id,
                t=t,
                name=name,
                type=type,
                team_id_in_possession=team_id,
                player_id=player_id,
                team_defencemen_on_ice_refs=team_defencemen_on_ice_refs,
                grade=grade,
                raw=e,
            )
        )
    return events