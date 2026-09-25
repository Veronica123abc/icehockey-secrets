"""Faceoff metrics. One group: who won the draw.

THE TWO VOCABULARIES DISAGREE ON HOW MANY EVENTS A DRAW IS, and the group has
to cover both. Verified over games 186449 + 186461 + 191848:

* ``playsequence_compiled`` -- 328 faceoffs, TWO per draw: 164 'successful'
  (the winner) and 164 'failed' (the loser). Nothing else.
* ``playsequence`` -- 492, THREE per draw: the same 164 + 164, plus 164
  carrying no outcome at all. That third one is the puck drop itself -- no
  team_id, no player_id, and a ``type`` that is the zone ('nz', 'hoz', 'hdz')
  rather than a result. All three share a timestamp.

So 'Untagged' is not decoration: without it Result would cover 328 of 492 on
the uncompiled path and the lane counts would silently disagree between
sources. With it, Result totals 328 and 492 respectively -- exhaustive on
both. The untagged events carry no team, so ``for_team`` drops them from
either side of :func:`get_full_data`; they are visible only in the whole-
population lanes.
"""
from __future__ import annotations

from hockey.model.events import Event
from hockey.derive.filter_group import FilterGroups, Predicate, for_team


def is_won(event: Event) -> bool:
    return event.outcome == 'successful'


def is_lost(event: Event) -> bool:
    return event.outcome == 'failed'


def is_untagged(event: Event) -> bool:
    """The uncompiled vocabulary's neutral puck-drop record."""
    return event.outcome not in ('successful', 'failed')


FACEOFF_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {'Won': is_won, 'Lost': is_lost, 'Untagged': is_untagged},
}

FACEOFFS = FilterGroups('faceoff', FACEOFF_FILTERS, 'Faceoffs')


def get_full_data(game) -> dict:
    """team id -> {lane key: events}. What ``golden.py`` sweeps."""
    faceoffs = [e for e in game.events if e.name == FACEOFFS.name]
    return {team: FACEOFFS.rows(for_team(faceoffs, team))
            for team in (game.info.home_team.id, game.info.away_team.id)}
