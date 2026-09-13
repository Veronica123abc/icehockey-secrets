#!/usr/bin/python
"""Dump-in metrics.

Two populations live here, each with its own filter dictionary:

* ``dumpin`` -- the puck event, one per attempt. Carries the dumping player's
  location ('westofdot', 'midice', 'eastofdot') and the technique ('rim',
  'crossice', 'soft', 'straight') in flags, and dump-vs-chip in ``type``.
* ``dumpinrecovery`` -- who picked the puck up afterwards, and what came of
  it. ``type`` is a concatenation: an 'offensive'/'defensive' prefix (the
  dumping team vs the opposition), optionally 'selfchipin', then the same
  withplay/withshotonnet/withslotshot decorations that appear in flags.

``dumpinentry`` is 1:1 with ``dumpin`` (150/150 over two games) and is the
event whose outcome says whether the dumping team recovered; it is exposed
through :func:`dumpin_entry` but is not a filtered population of its own,
since every filterable attribute it carries is also on one of the two above.

Group exhaustiveness, verified over games 186461 + 191848 (150 dump-ins):
Type 129+21, Location 65+31+54 and Result 122+28 each total 150 exactly.
Technique covers only 122 -- 28 attempts carry no technique flag -- so that
group has an explicit 'Untagged' item to keep it exhaustive.
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


# Dump-in type. 'chip' and 'dump' are the only two values, and they live on
# the dumpin event -- NOT on dumpinentry, whose type holds the shot
# decorations instead.
def is_dump(event: Event) -> bool:
    return 'dump' in event.type


def is_chip(event: Event) -> bool:
    return 'chip' in event.type


# Technique, from flags.
def is_rim(event: Event) -> bool:
    return 'rim' in event.flags


def is_crossice(event: Event) -> bool:
    return 'crossice' in event.flags


def is_soft(event: Event) -> bool:
    return 'soft' in event.flags


def is_straight(event: Event) -> bool:
    return 'straight' in event.flags


_TECHNIQUE_FLAGS = ('rim', 'crossice', 'soft', 'straight')


def is_untagged_technique(event: Event) -> bool:
    """No technique flag at all -- 28 of 150 attempts in the sample games."""
    return not any(flag in event.flags for flag in _TECHNIQUE_FLAGS)


# Location of the dumping player, from flags.
def is_west_of_dot(event: Event) -> bool:
    return 'westofdot' in event.flags


def is_midice(event: Event) -> bool:
    return 'midice' in event.flags


def is_east_of_dot(event: Event) -> bool:
    return 'eastofdot' in event.flags


# --- Recovery predicates --------------------------------------------------

def is_offensive_recovery(event: Event) -> bool:
    """Recovered by the dumping team."""
    return 'offensive' in event.type


def is_defensive_recovery(event: Event) -> bool:
    """Recovered by the defending team."""
    return 'defensive' in event.type


def is_self_chipin(event: Event) -> bool:
    """The dumping player recovered their own chip."""
    return 'selfchipin' in event.type


def is_not_self_chipin(event: Event) -> bool:
    return not is_self_chipin(event)


def with_play_after(event: Event) -> bool:
    return 'withplayafter' in event.flags


def without_play_after(event: Event) -> bool:
    return 'withplayafter' not in event.flags


def with_shot_onnet(event: Event) -> bool:
    return 'withshotonnet' in event.flags


def with_slotshot(event: Event) -> bool:
    return 'withslotshot' in event.flags


def with_no_shot(event: Event) -> bool:
    """Neither of the shot flags -- the complement that makes the group
    exhaustive. 'With Shot On Net' and 'With Slot Shot' deliberately overlap."""
    return 'shot' not in ''.join(event.flags)


def with_time_pressure(event: Event) -> bool:
    return 'timepressure' in event.flags


def with_contact_pressure(event: Event) -> bool:
    return 'contactpressure' in event.flags


def without_pressure(event: Event) -> bool:
    return not (with_time_pressure(event) or with_contact_pressure(event))


# --- Filter groups --------------------------------------------------------

Predicate = Callable[[Event], bool]

DUMPIN_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Type': {
        'Dump': is_dump,
        'Chip': is_chip,
    },
    'Technique': {
        'Rim': is_rim,
        'Cross-Ice': is_crossice,
        'Soft': is_soft,
        'Straight': is_straight,
        'Untagged': is_untagged_technique,
    },
    'Location': {
        'West of Dot': is_west_of_dot,
        'Mid-Ice': is_midice,
        'East of Dot': is_east_of_dot,
    },
}

DUMPIN_RECOVERY_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Recovering Team': {
        'Offensive': is_offensive_recovery,
        'Defensive': is_defensive_recovery,
    },
    'With Play After': {
        'With Play After': with_play_after,
        'With No Play After': without_play_after,
    },
    'With Shot': {
        'With Shot On Net': with_shot_onnet,
        'With Slot Shot': with_slotshot,
        'With No Shot': with_no_shot,
    },
    'Self Chip-In': {
        'Self Chip-In': is_self_chipin,
        'Not Self Chip-In': is_not_self_chipin,
    },
    'Pressure': {
        'Time Pressure': with_time_pressure,
        'Contact Pressure': with_contact_pressure,
        'No Pressure': without_pressure,
    },
}


# --- Base sets ------------------------------------------------------------

def all_dumpins(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every dump-in attempt, one per puck event."""
    events = [e for e in game.events if e.name == 'dumpin']
    return _for_team(events, team_id) if team_id else events


def all_dumpin_recoveries(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every dump-in recovery, by either team."""
    events = [e for e in game.events if e.name == 'dumpinrecovery']
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


def dumpins_matching(dumpins: Iterable[Event], group: str, item: str) -> list[Event]:
    """Dump-ins passing one named filter item."""
    return _matching(dumpins, DUMPIN_FILTERS, group, item)


def filter_dumpins(dumpins: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_dumpins(dumpins, Result=['Successful'], Type=['Chip'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return _apply(dumpins, DUMPIN_FILTERS, **selections)


def group_breakdown(dumpins: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given dump-ins."""
    return _breakdown(dumpins, DUMPIN_FILTERS)


def check_groups_exhaustive(dumpins: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every dump-in."""
    return _exhaustive(dumpins, DUMPIN_FILTERS)


def recoveries_matching(recoveries: Iterable[Event], group: str, item: str) -> list[Event]:
    return _matching(recoveries, DUMPIN_RECOVERY_FILTERS, group, item)


def filter_recoveries(recoveries: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    return _apply(recoveries, DUMPIN_RECOVERY_FILTERS, **selections)


def recovery_group_breakdown(recoveries: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    return _breakdown(recoveries, DUMPIN_RECOVERY_FILTERS)


def check_recovery_groups_exhaustive(recoveries: Iterable[Event]) -> dict[str, bool]:
    return _exhaustive(recoveries, DUMPIN_RECOVERY_FILTERS)


# --- Named sets kept for existing callers ---------------------------------

def dumpin(game: Game) -> Iterable[Event]:
    """Dump-in ENTRY events -- what this has always returned. Prefer
    :func:`all_dumpins` for the puck event carrying type and location."""
    return [e for e in game.events if e.name == 'dumpinentry']


def dumpin_entry(game: Game) -> Iterable[Event]:
    # A successful dumpinentry <=> the dumping team recovered.
    return [e for e in game.events if e.name == 'dumpinentry']


def chipin(game: Game) -> Iterable[Event]:
    """Chip-ins. Reads the dumpin event, where 'chip' actually lives -- the
    previous version filtered dumpinentry types and so always returned []."""
    return [e for e in all_dumpins(game) if is_chip(e)]


def dumpin_recovery(game: Game) -> Iterable[Event]:
    """Recoveries by the dumping team."""
    return [e for e in all_dumpin_recoveries(game) if is_offensive_recovery(e)]


# --- Helpers --------------------------------------------------------------

def _for_team(events: Iterable[Event], team_id: int | str) -> list[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        dumpins = all_dumpins(game, team_id)
        recoveries = all_dumpin_recoveries(game, team_id)

        out = {'All Dump-Ins': dumpins}
        for group, items in group_breakdown(dumpins).items():
            for item, events in items.items():
                out[f'{group} - {item}'] = events

        out['All Dump-In Recoveries'] = recoveries
        for group, items in recovery_group_breakdown(recoveries).items():
            for item, events in items.items():
                out[f'Recovery {group} - {item}'] = events

        res[team_id] = out
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDUMP-IN STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)

    dumpins = all_dumpins(game)
    print("\nexhaustiveness:", check_groups_exhaustive(dumpins))
    print("recovery exhaustiveness:",
          check_recovery_groups_exhaustive(all_dumpin_recoveries(game)))
    print("successful chips:",
          len(filter_dumpins(dumpins, Type=['Chip'], Result=['Successful'])))
