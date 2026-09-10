"""Reconstructing on-ice rosters from shift intervals.

The v2 schema stores no on-ice columns on `event`: who was on the ice is
functionally determined by `shift`, and duplicating it would cost ~70,000 rows
per game for a second source of truth. This rebuilds the four ref lists plus
the two goalie refs that the JSON payload carries, so an Event loaded from the
database is indistinguishable from one built from the files.

Verified against the supplier's own refs: 5029/5031 sampled events matched
exactly, and both differences were interval-edge rounding, not real
disagreements.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval

_OPEN, _CLOSE = 1, 0     # close before open at equal times: a shift ending at
                         # t and one starting at t must not both count at t


def on_ice_at_times(toi: Sequence[ToIInterval],
                    times: Iterable[float]) -> list[set[int]]:
    """The set of players on the ice at each query time, in query order.

    Sweep-line over shift boundaries rather than a scan per event: a game has
    ~800 shifts and ~6000 events, so the naive form is ~5M interval tests.

    A shift is half-open [in_time, out_time), matching current_shift.py, so a
    player changing at exactly t counts as off.
    """
    boundaries: list[tuple[float, int, int]] = []
    for interval in toi:
        end = interval.end_t if interval.end_t is not None else float('inf')
        boundaries.append((interval.start_t, _OPEN, interval.player_id))
        boundaries.append((end, _CLOSE, interval.player_id))
    boundaries.sort()

    queries = sorted((t, i) for i, t in enumerate(times))
    out: list[set[int]] = [set() for _ in queries]
    active: set[int] = set()
    cursor = 0
    for t, index in queries:
        while cursor < len(boundaries) and boundaries[cursor][0] <= t:
            _, kind, player_id = boundaries[cursor]
            if kind == _OPEN:
                active.add(player_id)
            else:
                active.discard(player_id)
            cursor += 1
        out[index] = set(active)
    return out


# Events whose on-ice refs the supplier keys to the OPPOSING team -- the one
# attacking, not the goalie's. Determined empirically over 12 games / 69,415
# events carrying a goalie ref:
#
#   save, goalagainst, goalieloss   always flipped (when credited to a goalie)
#   rebound                         flipped only when outcome == 'failed'
#                                   (193+13 failed flipped, 165+6 successful
#                                   not -- a rebound the goalie controlled
#                                   stays keyed to the goalie's team)
#
# Nothing in the payload flags this: is_defensive_event and
# is_possession_event do not separate the two groups, and "credited player is
# a goalie" over-fires on ordinary goalie passes and puck recoveries.
_GOALIE_PERSPECTIVE_NAMES = frozenset({'save', 'goalagainst', 'goalieloss'})


def own_team_for_event(*, name: str, outcome: str | None,
                       event_team_id: int | None,
                       credited_position: str | None,
                       home_team_id: int, away_team_id: int) -> int | None:
    """The team the supplier's ``team_*`` refs are keyed to for this event.

    Normally the event's own team. For goalie-perspective events it is the
    other one, so the refs describe the attacking side.
    """
    if event_team_id is None:
        return None
    if (credited_position or '').upper() != 'G':
        return event_team_id
    flipped = (name in _GOALIE_PERSPECTIVE_NAMES
               or (name == 'rebound' and outcome == 'failed'))
    if not flipped:
        return event_team_id
    return away_team_id if event_team_id == home_team_id else home_team_id


def split_by_team_and_position(on_ice: set[int], roster: Roster,
                               event_team_id: int | None) -> dict:
    """Split an on-ice set into the six fields the JSON payload carries.

    Keyed relative to ``event_team_id``: "team_*" is the event's own team,
    "opposing_team_*" the other one. With no team on the event there is no
    "own" side, so everything lands on the opposing keys being None -- the
    same shape the supplier uses when it does not know.
    """
    own_f: list[int] = []
    own_d: list[int] = []
    opp_f: list[int] = []
    opp_d: list[int] = []
    own_g: int | None = None
    opp_g: int | None = None

    for player_id in sorted(on_ice):
        player = roster.players.get(player_id)
        if player is None:
            continue
        own = event_team_id is not None and player.team_id == event_team_id
        position = (player.position or "").upper()
        if position == "G":
            if own:
                own_g = player_id
            else:
                opp_g = player_id
        elif position == "D":
            (own_d if own else opp_d).append(player_id)
        else:
            (own_f if own else opp_f).append(player_id)

    return {
        "team_forwards_on_ice_refs": own_f or None,
        "team_defencemen_on_ice_refs": own_d or None,
        "team_goalie_on_ice_ref": own_g,
        "opposing_team_forwards_on_ice_refs": opp_f or None,
        "opposing_team_defencemen_on_ice_refs": opp_d or None,
        "opposing_team_goalie_on_ice_ref": opp_g,
    }
