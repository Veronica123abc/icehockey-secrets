#!/usr/bin/python
"""Possession metrics.

An event with name="possession" is a child event hanging off a base event (the
puck event that established the possession: pass, shot, puckprotection,
dumpin, dumpout). Possession events exist only in the compiled vocabulary.

:data:`POSSESSION_FILTERS` covers what can be read off the possession event
itself. Two things deliberately sit OUTSIDE the dictionary because they need
the base event, which an ``Event -> bool`` predicate cannot reach:

* SportLogIQ counts a possession as successful only when BOTH the possession
  event and its base event are successful -- see this folder's CLAUDE.md. Over
  games 186461 + 191848, 2134 possession events are successful but only 1751
  of those also have a successful base. That definition lives in
  :func:`successful_possessions`, and the Result group's 'Successful' item is
  explicitly the possession event's OWN outcome, not this.
* Which kind of play established the possession, in
  :func:`base_event_breakdown`.

Group exhaustiveness, verified over the same two games (2475 possessions):
Result 2134+341 and Zone 835+371+1269 each total 2475.

The group machinery itself lives in ``hockey.derive.filter_group``.
"""
from __future__ import annotations

from collections.abc import Iterable

from hockey.model.events import Event
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.base_events import index_by_event_id, base_event
from hockey.derive.filter_group import FilterGroups, Predicate, for_team

# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_successful(event: Event) -> bool:
    """The possession event's OWN outcome. Not SportLogIQ's definition of a
    successful possession -- see :func:`successful_possessions`."""
    return event.outcome == 'successful'


def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'


def in_dz(event: Event) -> bool:
    return event.zone == 'dz'


def in_nz(event: Event) -> bool:
    return event.zone == 'nz'


def in_oz(event: Event) -> bool:
    return event.zone == 'oz'


# --- Filter groups --------------------------------------------------------

POSSESSION_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Zone': {
        'DZ': in_dz,
        'NZ': in_nz,
        'OZ': in_oz,
    },
}

POSSESSIONS = FilterGroups('possession', POSSESSION_FILTERS)


# --- Base sets ------------------------------------------------------------

def possessions(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'possession']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def possessions_matching(events: Iterable[Event], group: str, item: str) -> list[Event]:
    """Possessions passing one named filter item."""
    return POSSESSIONS.matching(events, group, item)


def filter_possessions(events: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_possessions(possessions, Result=['Failed'], Zone=['DZ'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return POSSESSIONS.filter(events, **selections)


def group_breakdown(events: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given possessions."""
    return POSSESSIONS.breakdown(events)


def check_groups_exhaustive(events: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every possession."""
    return POSSESSIONS.check_exhaustive(events)


# --- Base-event-dependent sets -------------------------------------------
# These need the base event and so cannot be predicates in the dictionary.

def successful_possessions(game: Game) -> list[Event]:
    """Possessions SportLogIQ counts as successful.

    Both the possession event and the base event it hangs off must be
    successful -- see this folder's CLAUDE.md. Compiled vocabulary only.
    """
    index = index_by_event_id(game.events)
    out = []
    for e in possessions(game):
        if e.outcome != 'successful':
            continue
        base = base_event(e, index)
        if base is not None and base.outcome == 'successful':
            out.append(e)
    return out


def failed_possessions(game: Game) -> list[Event]:
    """Every possession that is not successful by the definition above."""
    successful = {id(e) for e in successful_possessions(game)}
    return [e for e in possessions(game) if id(e) not in successful]


def turnovers(game: Game) -> list[Event]:
    return [e for e in possessions(game) if e.outcome == 'failed']


def base_event_breakdown(game: Game, team_id: int | str | None = None) -> dict[str, list[Event]]:
    """Possessions grouped by the kind of play that established them.

    Observed base events: pass, shot, puckprotection, dumpin, dumpout, soshot.
    A possession whose base cannot be resolved lands under '<unresolved>'
    rather than being dropped.
    """
    index = index_by_event_id(game.events)
    out: dict[str, list[Event]] = {}
    for e in possessions(game, team_id):
        base = base_event(e, index)
        out.setdefault(base.name if base is not None else '<unresolved>', []).append(e)
    return out


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    all_possessions = possessions(game)
    successful = successful_possessions(game)
    failed = failed_possessions(game)
    all_turnovers = turnovers(game)

    for team_id in team_ids:
        team_possessions = for_team(all_possessions, team_id)

        res[team_id] = {
            'All Possessions': team_possessions,
            **POSSESSIONS.rows(team_possessions),
            # SportLogIQ's definition: possession AND base event both successful.
            'Successful Possessions': for_team(successful, team_id),
            'Failed Possessions': for_team(failed, team_id),
            'Turnovers': for_team(all_turnovers, team_id),
            **{f'Base Event - {name}': events
               for name, events in base_event_breakdown(game, team_id).items()},
        }

    res[team_ids[0]]['Takeovers'] = res[team_ids[1]]['Turnovers']
    res[team_ids[1]]['Takeovers'] = res[team_ids[0]]['Turnovers']
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nPOSSESSION STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)

    all_possessions = possessions(game)
    print("\nexhaustiveness:", check_groups_exhaustive(all_possessions))
    print("failed DZ possessions:",
          len(filter_possessions(all_possessions, Result=['Failed'], Zone=['DZ'])))
