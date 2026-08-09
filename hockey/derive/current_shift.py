from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING



from hockey.model.toi import ToIInterval, CurrentShiftTOI, PlayerCurrentShiftToi

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

def find_intervals(intervals, queries):
    starts = sorted((s, i) for i, (s, e) in enumerate(intervals))
    ends   = sorted((e, i) for i, (s, e) in enumerate(intervals))
    q_sorted = sorted((q, j) for j, q in enumerate(queries))
    active = []
    result = [[] for _ in queries]
    i = j = 0
    for t, q_idx in q_sorted:

        # START: inkludera t_s <= t
        while i < len(starts) and starts[i][0] <= t:
            active.append(starts[i][1])
            i += 1

        # END: exkludera t_e <= t
        while j < len(ends) and ends[j][0] <= t:
            active.remove(ends[j][1])
            j += 1

        # QUERY snapshot
        result[q_idx] = (t, active.copy())

    return result


def current_shift_toi(
    game: Game,
    game_time: float,
    *,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> dict[int, dict[str, Any]]: #dict[int, list[dict[str, Any]]]: #dict[int, list[dict]]: #dict[int, dict[str, Any]]:
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

    # whistle_t = _last_whistle_time(game, game_time) if reset_on_whistle else None

    # Collect active intervals at this moment
    # by_team: dict[int, list[ToIInterval]] = {home_id: [], away_id: []}
    # by_team: dict[int, list[dict]] = {home_id: [], away_id: []}
    by_team: dict[int, dict[str, Any]] = {
        home_id: {"players": [], "total_team_shift_toi": 0},
        away_id: {"players": [], "total_team_shift_toi": 0}
    }
    for x in game.toi:
        if x.team_id not in by_team:
            continue
        if x.start_t <= game_time and (x.end_t is None or game_time < x.end_t):
            if (not include_goalies) and _is_goalie(game, x.player_id):
                continue
            item = {"player_id": x.player_id, "toi": game_time - x.start_t}     # "player_position": _player_position(game, x.player_id)}
            #by_team[x.team_id].append(x)
            by_team[x.team_id]["players"].append(item)
            by_team[x.team_id]["total_team_shift_toi"] += game_time - x.start_t

    # for team_id in team_ids:
    #     total = sum([k['toi'] for k in by_team[team_id]])
    #     by_team[team_id].append({"total": total})

    return by_team


def current_shift_toi_series(game: Game, query_times:list[float], include_goalies=False):
    pos_by_player = {pid: p.position for pid, p in game.roster.players.items()}
    game_toi = [toi for toi in game.toi if pos_by_player[toi.player_id] != 'G'] if not include_goalies else game.toi
    player_intervals = [(s.start_t, s.end_t) for s in game_toi] #game.toi]
    intervals = find_intervals(player_intervals, query_times)
    snapshots = []
        # stable ordering (optional)

    for interval in intervals:
        query_time = interval[0]
        shifts = [game_toi[k] for k in interval[1]]
        out: dict[int, dict[str, Any]] = {}
        for team_id in [game.info.home_team.id, game.info.away_team.id]:
            team_shifts = [shift for shift in shifts if shift.team_id == team_id]

            players_payload = []
            total = 0.0
            for shift in team_shifts:
                players_payload.append(
                    {
                        "player_id": shift.player_id,
                        "current_shift_toi": query_time - shift.start_t,
                    }
                )
                total += query_time - shift.start_t
            out[team_id] = {
                "team_id": team_id,
                "players": players_payload,
                "total_team_shift_toi": total,
                "average_team_shift_toi": total / len(team_shifts) if len(team_shifts) else 0.0,
            }
        snapshots.append(out)
    return snapshots


#def _current_shift_toi_2(toi_intervals: list[ToIInterval], game: Game) -> CurrentShiftTOI:

