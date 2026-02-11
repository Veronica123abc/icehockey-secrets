from __future__ import annotations

from typing import Any, Optional

from hockey.model.game import Game
from hockey.model.toi import ToIInterval


def _is_goalie(game: Game, player_id: int) -> bool:
    p = game.roster.players.get(player_id)
    return (p is not None) and (p.position == "G")


def _player_position(game: Game, player_id: int) -> Optional[str]:
    p = game.roster.players.get(player_id)
    return p.position if p is not None else None


def current_shift_toi(
    game: Game,
    game_time: float,
    *,
    include_goalies: bool = False,
) -> dict[int, dict[str, Any]]:
    """
    For a given game_time (seconds), return per-team:
      - all players currently on ice
      - each player's time on ice since start of their current shift
      - player's position (from roster if available)
      - total_team_shift_toi: sum of all current_shift_toi values for that team

    Output shape:
    {
      <team_id>: {
        "team_id": <team_id>,
        "players": [
           {"player_id": ..., "player_position": ..., "current_shift_toi": ...},
           ...
        ],
        "total_team_shift_toi": ...
      },
      ...
    }
    """
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    team_ids = (home_id, away_id)

    # Collect active intervals at this moment
    by_team: dict[int, list[ToIInterval]] = {home_id: [], away_id: []}

    for x in game.toi:
        if x.team_id not in by_team:
            continue
        if x.start_t <= game_time and (x.end_t is None or game_time < x.end_t):
            if (not include_goalies) and _is_goalie(game, x.player_id):
                continue
            by_team[x.team_id].append(x)

    out: dict[int, dict[str, Any]] = {}

    for team_id in team_ids:
        players_payload = []
        total = 0.0

        # sort for stable output (by longer shift first, then player id)
        intervals = sorted(
            by_team[team_id],
            key=lambda x: (-(game_time - x.start_t), x.player_id),
        )

        for x in intervals:
            toi_now = float(game_time - x.start_t)
            total += toi_now
            players_payload.append(
                {
                    "player_id": x.player_id,
                    "player_position": _player_position(game, x.player_id),
                    "current_shift_toi": toi_now,
                }
            )

        out[team_id] = {
            "team_id": team_id,
            "players": players_payload,
            "total_team_shift_toi": total,
        }

    return out