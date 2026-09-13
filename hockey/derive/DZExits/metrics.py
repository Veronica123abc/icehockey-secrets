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
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


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

Predicate = Callable[[Event], bool]

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


# --- Base sets ------------------------------------------------------------

def all_controlled_exits(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every controlled exit attempt, successful or not."""
    events = [e for e in game.events if e.name == 'controlledexit']
    return _for_team(events, team_id) if team_id else events


def all_dumpouts(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'dumpout']
    return _for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def _matching(events: Iterable[Event], filters: dict, group: str, item: str) -> list[Event]:
    try:
        predicate = filters[group][item]
    except KeyError:
        raise KeyError(f"unknown filter {group!r}/{item!r}; groups are "
                       f"{sorted(filters)}") from None
    return [e for e in events if predicate(e)]


def _apply(events: Iterable[Event], filters: dict, **selections: Iterable[str]) -> list[Event]:
    events = list(events)
    for raw_group, items in selections.items():
        group = raw_group.replace('_', ' ')
        if group not in filters:
            raise KeyError(f"unknown filter group {group!r}; "
                           f"groups are {sorted(filters)}")
        if isinstance(items, str):
            items = [items]
        predicates = [filters[group][i] for i in items]
        events = [e for e in events if any(p(e) for p in predicates)]
    return events


def _breakdown(events: Iterable[Event], filters: dict) -> dict[str, dict[str, list[Event]]]:
    events = list(events)
    return {group: {item: [e for e in events if predicate(e)]
                    for item, predicate in items.items()}
            for group, items in filters.items()}


def _exhaustive(events: Iterable[Event], filters: dict) -> dict[str, bool]:
    events = list(events)
    out = {}
    for group, items in filters.items():
        covered = {id(e) for e in events if any(p(e) for p in items.values())}
        out[group] = len(covered) == len(events)
    return out


def exits_matching(exits: Iterable[Event], group: str, item: str) -> list[Event]:
    """Controlled exits passing one named filter item."""
    return _matching(exits, EXIT_FILTERS, group, item)


def filter_exits(exits: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_exits(exits, Result=['Successful'], Type=['Carry'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return _apply(exits, EXIT_FILTERS, **selections)


def group_breakdown(exits: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given exits."""
    return _breakdown(exits, EXIT_FILTERS)


def check_groups_exhaustive(exits: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every exit."""
    return _exhaustive(exits, EXIT_FILTERS)


def dumpouts_matching(dumpouts: Iterable[Event], group: str, item: str) -> list[Event]:
    return _matching(dumpouts, DUMPOUT_FILTERS, group, item)


def filter_dumpouts(dumpouts: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    return _apply(dumpouts, DUMPOUT_FILTERS, **selections)


def dumpout_group_breakdown(dumpouts: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    return _breakdown(dumpouts, DUMPOUT_FILTERS)


def check_dumpout_groups_exhaustive(dumpouts: Iterable[Event]) -> dict[str, bool]:
    return _exhaustive(dumpouts, DUMPOUT_FILTERS)


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

def _for_team(events: Iterable[Event], team_id: int | str) -> list[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        exits = all_controlled_exits(game, team_id)
        outs = all_dumpouts(game, team_id)
        recoveries = _for_team(opposition_dumpin_recoveries(game), team_id)

        out = {'All Controlled Exits': exits}
        for group, items in group_breakdown(exits).items():
            for item, events in items.items():
                out[f'{group} - {item}'] = events

        out['All Dump-Outs'] = outs
        for group, items in dumpout_group_breakdown(outs).items():
            for item, events in items.items():
                out[f'Dump-Out {group} - {item}'] = events

        out['Opposition Dumpin Recoveries'] = recoveries
        out['Successful Opposition Dumpin Recoveries'] = [
            e for e in recoveries if is_successful(e)]

        res[team_id] = out
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDZ EXIT STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir,
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
