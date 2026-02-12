from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING



from hockey.model.toi import ToIInterval
if TYPE_CHECKING:
    from hockey.model.game import Game

def _is_goalie(game: Game, player_id: int) -> bool:
    p = game.roster.players.get(player_id)
    return (p is not None) and (p.position == "G")


def _player_position(game: Game, player_id: int) -> Optional[str]:
    p = game.roster.players.get(player_id)
    return p.position if p is not None else None


def _last_whistle_time(game: Game, game_time: float) -> Optional[float]:
    """
    Return the last whistle event time <= game_time, or None if no whistle yet.
    Assumes game.events contains normalized playsequence events with type == "whistle".
    """
    last: Optional[float] = None
    for e in game.events:
        if e.name != "whistle":
            continue
        if e.t <= game_time and (last is None or e.t > last):
            last = e.t
    return last


def current_shift_toi(
    game: Game,
    game_time: float,
    *,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> dict[int, dict[str, Any]]:
    """
    For a given game_time (seconds), return per-team:
      - all players currently on ice
      - each player's time on ice since start of their current shift
      - optionally resets shift timer at last whistle (if reset_on_whistle=True)
      - player's position (from roster if available)
      - total_team_shift_toi: sum of all current_shift_toi values for that team
    """
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    team_ids = (home_id, away_id)

    whistle_t = _last_whistle_time(game, game_time) if reset_on_whistle else None

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

        def _toi_now(interval: ToIInterval) -> float:
            effective_start = interval.start_t
            if whistle_t is not None and whistle_t > effective_start:
                effective_start = whistle_t
            return float(game_time - effective_start)

        # sort for stable output (by longer shift first, then player id)
        intervals = sorted(
            by_team[team_id],
            key=lambda x: (-_toi_now(x), x.player_id),
        )

        for x in intervals:
            toi_now = _toi_now(x)
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