"""Mapping v2 database event rows to :class:`Event`.

The v2 `event` table stores one merged vocabulary with column names matching
the supplier's JSON keys, so this is a near-straight mapping. Three things
still need doing:

* ``sl_event_id`` is a string (derived events carry "<child>-<base>"), and
  ``Event.event_id`` is an int -- so it goes into ``raw['event_id']``
  verbatim, and the typed field takes the int where there is one. That is
  exactly what the JSON path does, so metrics keying on
  ``get_raw('event_id')`` behave identically from either source.
* Flags come from ``event_flag`` and are passed in already grouped.
* The on-ice refs are not stored; the caller reconstructs them from ``shift``
  (see on_ice_from_shifts) and passes them in.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from hockey.model.events import Event

# Row columns copied straight into raw under the same name, so get_raw() sees
# what the JSON payload would have shown.
_RAW_PASSTHROUGH = (
    'game_time', 'period', 'period_time', 'name', 'type', 'outcome',
    'shorthand', 'zone', 'play_zone', 'play_section',
    'x_adj_coord', 'y_adj_coord',
    'current_possession', 'current_play_in_possession',
    'is_possession_event', 'is_last_play_of_possession',
    'is_possession_breaking', 'is_defensive_event',
    'team_skaters_on_ice', 'opposing_team_skaters_on_ice',
    'manpower_situation', 'score_differential',
    'expected_goals_all_shots', 'expected_goals_all_shots_grade',
    'expected_goals_on_net', 'expected_goals_on_net_grade',
)


def maybe_int(x) -> int | None:
    """The supplier's event ids are strings, and derived ones are not numeric."""
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class IdMaps:
    """DB primary key -> SportLogIQ id, for the players and teams in scope.

    Model objects use sl_ids throughout, matching the JSON path. For a single
    game these cover that game's roster; for a season query they must cover
    every game queried, or ids outside the map resolve to None.
    """
    player_db_to_sl: Mapping[int, int]
    team_db_to_sl: Mapping[int, int]

    def player(self, db_id) -> int | None:
        return self.player_db_to_sl.get(db_id) if db_id else None

    def team(self, db_id) -> int | None:
        return self.team_db_to_sl.get(db_id) if db_id else None


def event_from_row(row: Mapping, *, game_id: int, ids: IdMaps,
                   flags: list[str] | None = None,
                   on_ice: Mapping | None = None) -> Event:
    """One v2 event row -> Event.

    ``game_id`` is the SportLogIQ game id, not the row's ``game_id`` column
    (a DB primary key) -- a caller spanning several games resolves it per row.
    ``flags`` and ``on_ice`` come from the companion queries; both default to
    "none known" rather than "none present".
    """
    flags = list(flags or [])
    on_ice = dict(on_ice or {})

    raw = {key: row.get(key) for key in _RAW_PASSTHROUGH}
    # JSON names for the two id columns, so get_raw('event_id') works exactly
    # as it does on the file path -- base_events.py depends on this.
    raw['event_id'] = row.get('sl_event_id')
    raw['base_event_id'] = row.get('sl_base_event_id')
    raw['flags'] = flags
    raw.update(on_ice)

    return Event(
        game_id=game_id,
        t=float(row['game_time']),
        type=row.get('type') or "",
        name=row.get('name') or "",
        team_id_in_possession=ids.team(row.get('team_in_possession')),
        team_id=ids.team(row.get('team_id')),
        player_id=ids.player(row.get('player_id')),
        grade=row.get('expected_goals_all_shots_grade'),
        raw=raw,
        event_id=maybe_int(row.get('sl_event_id')),
        base_event_id=maybe_int(row.get('sl_base_event_id')),
        team_forwards_on_ice_refs=on_ice.get('team_forwards_on_ice_refs'),
        team_defencemen_on_ice_refs=on_ice.get('team_defencemen_on_ice_refs'),
        team_goalie_on_ice_ref=on_ice.get('team_goalie_on_ice_ref'),
        opposing_team_forwards_on_ice_refs=on_ice.get('opposing_team_forwards_on_ice_refs'),
        opposing_team_defencemen_on_ice_refs=on_ice.get('opposing_team_defencemen_on_ice_refs'),
        opposing_team_goalie_on_ice_ref=on_ice.get('opposing_team_goalie_on_ice_ref'),
        play_section=row.get('play_section'),
        expected_goals_all_shots=row.get('expected_goals_all_shots'),
        expected_goals_on_net=row.get('expected_goals_on_net'),
        expected_goals_on_net_grade=row.get('expected_goals_on_net_grade'),
        outcome=row.get('outcome') or None,
        flags=flags,
        current_possession=maybe_int(row.get('current_possession')),
        current_play_in_possession=maybe_int(row.get('current_play_in_possession')),
        zone=row.get('zone') or None,
        team_skaters_on_ice=maybe_int(row.get('team_skaters_on_ice')),
        opposing_team_skaters_on_ice=maybe_int(row.get('opposing_team_skaters_on_ice')),
    )
