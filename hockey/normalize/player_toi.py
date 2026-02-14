from __future__ import annotations

from typing import Optional

from hockey.model.toi import ToIInterval
from hockey.normalize.team_resolution import TeamResolver


def normalize_player_toi(
    *,
    game_id: int,
    raw_player_toi: dict,
    teams: TeamResolver,
) -> list[ToIInterval]:
    """
    Convert raw playerTOI events (IN/OUT) into intervals.

    Your sample contains:
      - player_reference_id: str
      - game_time: number
      - in_or_out: "IN"/"OUT"
      - team: display string (needs mapping -> id)
    """
    events = raw_player_toi.get("events", [])
    active_start: dict[int, float] = {}
    active_team: dict[int, Optional[int]] = {}
    intervals: list[ToIInterval] = []

    for e in events:
        player_id = int(str(e["player_reference_id"]).strip())
        t = float(e["game_time"])
        in_out = str(e.get("in_or_out", "")).upper()

        team_id = teams.team_id_from_string(e.get("team"))

        if in_out == "IN":
            active_start[player_id] = t
            active_team[player_id] = team_id
        elif in_out == "OUT":
            if player_id in active_start:
                intervals.append(
                    ToIInterval(
                        game_id=game_id,
                        team_id=active_team.get(player_id),
                        player_id=player_id,
                        start_t=active_start[player_id],
                        end_t=t,
                    )
                )
                del active_start[player_id]
                active_team.pop(player_id, None)
            else:
                pass
                #print("OUT event without prior IN")
                #raise ValueError(f"TOI OUT without prior IN for player {player_id} at t={t}")
        else:
            continue

    for player_id, start_t in active_start.items():
        intervals.append(
            ToIInterval(
                game_id=game_id,
                team_id=active_team.get(player_id),
                player_id=player_id,
                start_t=start_t,
                end_t=None,
            )
        )

    return intervals