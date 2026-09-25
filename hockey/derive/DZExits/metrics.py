#!/usr/bin/python
"""DZ exit metrics.

Two populations, each with its own filter dictionary:

* ``controlledexit`` -- an exit with possession retained. ``type`` packs both
  the method and the follow-up: 'carry', 'carrywithplay', 'pass',
  'passwithplay'. Note the "with play after" marker is in the TYPE here, not
  in flags as it is on dump-in recoveries and controlled entries.
* ``dumpout`` -- the puck sent out without possession, typed by route:
  'boards', 'ice', 'flip'.

Opposition dump-in recoveries (``dumpinrecovery`` with type 'defensive') are
an exit-adjacent event credited to the defending team; they are reported as a
named set rather than a filtered population, since ``dumpins.metrics`` owns
the recovery filters.

Group exhaustiveness, verified over games 186461 + 191848: for controlled
exits Result 269+95, Type 146+218 and With Play After 218+146 each total 364;
for dump-outs Result 72+53 and Type 67+42+16 each total 125.

The group machinery itself lives in ``hockey.derive.filter_group``.
"""
from __future__ import annotations

from collections.abc import Iterable

from hockey.model.events import Event
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.filter_group import FilterGroups, Predicate, for_team

# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_successful(event: Event) -> bool:
    return event.outcome == 'successful'


def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'


def is_carry(event: Event) -> bool:
    return 'carry' in (event.type or '')


def is_pass(event: Event) -> bool:
    return 'pass' in (event.type or '')


def with_play_after(event: Event) -> bool:
    """'withplay' is part of the controlledexit TYPE, not a flag."""
    return 'withplay' in (event.type or '')


def without_play_after(event: Event) -> bool:
    return not with_play_after(event)


# Dump-out route.
def is_off_boards(event: Event) -> bool:
    return 'boards' in (event.type or '')


def is_off_ice(event: Event) -> bool:
    return 'ice' in (event.type or '')


def is_flip(event: Event) -> bool:
    return 'flip' in (event.type or '')


# --- Filter groups --------------------------------------------------------

EXIT_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Type': {
        'Carry': is_carry,
        'Pass': is_pass,
    },
    'With Play After': {
        'With Play After': with_play_after,
        'With No Play After': without_play_after,
    },
}

DUMPOUT_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Type': {
        'Boards': is_off_boards,
        'Ice': is_off_ice,
        'Flip': is_flip,
    },
}

EXITS = FilterGroups('controlledexit', EXIT_FILTERS)
DUMPOUTS = FilterGroups('dumpout', DUMPOUT_FILTERS)


# --- Base sets ------------------------------------------------------------

def all_controlled_exits(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every controlled exit attempt, successful or not."""
    events = [e for e in game.events if e.name == 'controlledexit']
    return for_team(events, team_id) if team_id else events


def all_dumpouts(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'dumpout']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def filter_exits(exits: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_exits(exits, Result=['Successful'], Type=['Carry'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return EXITS.filter(exits, **selections)


def check_groups_exhaustive(exits: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every exit."""
    return EXITS.check_exhaustive(exits)


def check_dumpout_groups_exhaustive(dumpouts: Iterable[Event]) -> dict[str, bool]:
    return DUMPOUTS.check_exhaustive(dumpouts)


# --- Named sets kept for existing callers ---------------------------------

def controlled_exits(game: Game) -> Iterable[Event]:
    """Successful controlled exits only -- what this has always returned.
    Use :func:`all_controlled_exits` for attempts."""
    return [e for e in game.events
            if e.name == 'controlledexit' and e.outcome == 'successful']


def dz_carry_outs(game: Game) -> Iterable[Event]:
    return [e for e in all_controlled_exits(game) if is_carry(e)]


def exit_pass(game: Game) -> Iterable[Event]:
    return [e for e in all_controlled_exits(game) if is_pass(e)]


def dumpouts(game: Game) -> Iterable[Event]:
    return all_dumpouts(game)


def opposition_dumpin_recoveries(game: Game) -> Iterable[Event]:
    """Dump-ins by the opposition that this team recovered."""
    return [e for e in game.events
            if e.name == 'dumpinrecovery' and e.type == 'defensive']


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        exits = all_controlled_exits(game, team_id)
        outs = all_dumpouts(game, team_id)
        recoveries = for_team(opposition_dumpin_recoveries(game), team_id)

        res[team_id] = {
            'All Controlled Exits': exits,
            **EXITS.rows(exits),
            'All Dump-Outs': outs,
            **DUMPOUTS.rows(outs, 'Dump-Out '),
            'Opposition Dumpin Recoveries': recoveries,
            'Successful Opposition Dumpin Recoveries': [
                e for e in recoveries if is_successful(e)],
        }
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDZ EXIT STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)

    exits = all_controlled_exits(game)
    print("\nexhaustiveness:", check_groups_exhaustive(exits))
    print("dump-out exhaustiveness:",
          check_dumpout_groups_exhaustive(all_dumpouts(game)))
    print("successful carries with play after:",
          len(filter_exits(exits, Result=['Successful'], Type=['Carry'],
                           With_Play_After=['With Play After'])))
