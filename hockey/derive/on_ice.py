from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hockey.model.events import Event
from hockey.model.toi import ToIInterval
from hockey.model.roster import Roster


@dataclass(frozen=True, slots=True)
class OnIceAtEvent:
    game_id: int
    t: float
    event_type: str
    team_id_in_possession: Optional[int]
    player_id: Optional[int]  # actor (if known)
    home_on_ice: tuple[int, ...]
    away_on_ice: tuple[int, ...]


def _players_on_ice_at(toi: list[ToIInterval], t: float, team_id: int) -> list[int]:
    out: list[int] = []
    for x in toi:
        if x.team_id != team_id:
            continue
        if x.start_t <= t and (x.end_t is None or t < x.end_t):
            out.append(x.player_id)
    return out


def on_ice_at_events(
    *,
    events: list[Event],
    toi: list[ToIInterval],
    home_team_id: int,
    away_team_id: int,
    drop_goalies: bool = False,
    goalie_position_lookup: Optional[dict[int, str]] = None,
    roster: Optional[Roster] = None,
) -> list[OnIceAtEvent]:
    """
    Return one row per event with home/away on-ice player ids.

    Backwards-compatible:
      - existing callers can keep using goalie_position_lookup
    New option:
      - pass roster=game.roster and drop_goalies=True to filter goalies automatically
    """
    if drop_goalies and goalie_position_lookup is None and roster is not None:
        goalie_position_lookup = {pid: p.position for pid, p in roster.players.items()}

    res: list[OnIceAtEvent] = []

    for e in events:
        home = _players_on_ice_at(toi, e.t, home_team_id)
        away = _players_on_ice_at(toi, e.t, away_team_id)

        if drop_goalies and goalie_position_lookup is not None:
            home = [pid for pid in home if goalie_position_lookup.get(pid) != "G"]
            away = [pid for pid in away if goalie_position_lookup.get(pid) != "G"]

        res.append(
            OnIceAtEvent(
                game_id=e.game_id,
                t=e.t,
                event_type=e.type,
                team_id_in_possession=e.team_id_in_possession,
                player_id=e.player_id,
                home_on_ice=tuple(sorted(home)),
                away_on_ice=tuple(sorted(away)),
            )
        )

    return res


def strength_at_event(row: OnIceAtEvent) -> str:
    """
    Basic strength label like "5v5", "5v4", ...
    (Counts are skaters if you drop goalies; otherwise includes goalies.)
    """
    return f"{len(row.home_on_ice)}v{len(row.away_on_ice)}"