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


def current_shift_toi_series_3(
    game: "Game",
    *,
    start_time: int = 0,
    end_time: int = 3600,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> list[dict[int, dict[str, Any]]]:
    epsilon = 1e-6
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    team_ids = (home_id, away_id)
    for team_id in team_ids:
        ins = sorted(set(list([k.start_t for k in game.toi if k.team_id == team_id])))
        outs = sorted(set(list([k.end_t for k in game.toi if k.team_id == team_id])))
        times = ins + outs
        intervals = [b - a for a, b in zip(times[:-1], times[1:])]
        res = [0]*(end_time - start_time)
        anchors = []
        for t in times:
            anchors.append(((t-epsilon),
                           game.current_shift_toi(t-epsilon, reset_on_whistle=False)[home_id]['total_team_shift_toi']))
            anchors.append(((t),
                           game.current_shift_toi(t, reset_on_whistle=False)[home_id]['total_team_shift_toi']))
        k=my_interpolator(anchors)
        res = [k(t) for t in range(start_time, end_time)]
        return res


def current_shift_toi_series_2(
    game: "Game",
    *,
    start_time: int = 0,
    end_time: int = 3600,
    include_goalies: bool = False,
    reset_on_whistle: bool = True,
) -> list[dict[int, dict[str, Any]]]:
    epsilon = 1e-6
    home_id = game.info.home_team.id
    away_id = game.info.away_team.id
    team_ids = (home_id, away_id)
    for team_id in team_ids:
        ins = sorted(set(list([k.start_t for k in game.toi if k.team_id == team_id])))
        outs = sorted(set(list([k.end_t for k in game.toi if k.team_id == team_id])))
        times = ins + outs
        intervals = [b - a for a, b in zip(times[:-1], times[1:])]
        res = [0]*(end_time - start_time + 1)
        for t in times:
            print(t)
            res[int(t)] = game.current_shift_toi(t - epsilon, reset_on_whistle=False)[home_id]['total_team_shift_toi']
        a = np.array(res, dtype=float)
        x = np.arange(len(a))
        mask = a != 0   # known values are the non-zero ones
        result = np.interp(x, x[mask], a[mask])


def current_shift_toi_series(
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