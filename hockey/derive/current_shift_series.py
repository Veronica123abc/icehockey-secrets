from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional, TYPE_CHECKING
import numpy as np
from hockey.model.toi import ToIInterval

if TYPE_CHECKING:
    from hockey.model.game import Game


def _is_goalie(game: "Game", player_id: int) -> bool:
    p = game.roster.players.get(player_id)
    return (p is not None) and (p.position == "G")


class my_interpolator:
    def __init__(self, points):
        points = sorted(points)
        self.t = np.array([t for t, _ in points], dtype=float)
        self.v = np.array([v for _, v in points], dtype=float)

    def __call__(self, t):
        return float(np.interp(t, self.t, self.v))

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


def current_shift_toi_series_old(
    game: "Game",
    *,
    start_time: int = 0,
    end_time: int = 3600,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> list[dict[int, dict[str, Any]]]:
    """
    Fast version of calling game.current_shift_toi(t) for every second.

    Returns a list of length (end_time - start_time) where each element is:
      {
        team_id: {
          "team_id": team_id,
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

    # Whistles by second
    whistle_seconds: set[int] = set()
    if reset_on_whistle:
        for e in game.events:
            if getattr(e, "name", None) == "whistle":
                whistle_seconds.add(int(e.t))

    # Build IN/OUT schedules by integer second
    ins: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    outs: dict[int, list[tuple[int, int]]] = defaultdict(list)

    for x in game.toi:
        if x.team_id not in team_ids:
            continue
        if (not include_goalies) and _is_goalie(game, x.player_id):
            continue

        in_sec = int(x.start_t)
        ins[in_sec].append((x.team_id, x.player_id, x.start_t))



        if x.end_t is not None:
            out_sec = int(x.end_t)
            outs[out_sec].append((x.team_id, x.player_id))

    # Active state: for each team, map player_id -> effective_start_time (float)
    active_start: dict[int, dict[int, float]] = {home_id: {}, away_id: {}}
    pos_by_player = {pid: p.position for pid, p in game.roster.players.items()}

    snapshots: list[dict[int, dict[str, Any]]] = []

    for t in range(start_time, end_time):

        # Apply OUTs first at second t (players whose shift ended at time ~t)
        for team_id, player_id in outs.get(t, []):
            active_start[team_id].pop(player_id, None)

        # Apply INs
        for team_id, player_id, start_t in ins.get(t, []):
            active_start[team_id][player_id] = start_t

        # Whistle reset: everyone currently on ice gets effective start reset to t
        if reset_on_whistle and t in whistle_seconds:
            for team_id in team_ids:
                for player_id in list(active_start[team_id].keys()):
                    active_start[team_id][player_id] = float(t)

        out: dict[int, dict[str, Any]] = {}
        for team_id in team_ids:
            players_payload = []
            total = 0.0

            # stable ordering (optional)
            for player_id in sorted(active_start[team_id].keys()):
                start_t = active_start[team_id][player_id]
                toi_now = float(t - start_t)
                total += toi_now
                players_payload.append(
                    {
                        "player_id": player_id,
                        "player_position": pos_by_player.get(player_id),
                        "current_shift_toi": toi_now,
                    }
                )

            out[team_id] = {
                "team_id": team_id,
                "players": players_payload,
                "total_team_shift_toi": total,
            }

        snapshots.append(out)

    return snapshots

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



