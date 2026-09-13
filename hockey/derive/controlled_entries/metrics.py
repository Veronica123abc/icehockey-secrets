#!/usr/bin/python
from __future__ import annotations
from pathlib import Path

from collections.abc import Callable, Iterable
from hockey.model.events import Event
from hockey.data_collection.sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.event_filter import EventFilter
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
filter = EventFilter(settings)

# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).


def is_pass(event: Event) -> bool:
    return 'pass' in event.type

def is_carry(event: Event) -> bool:
    return 'carry' in event.type

def with_play_after(event: Event) -> bool:
    return 'withplayafter' in event.flags

def without_play_after(event: Event) -> bool:
    return 'withplayafter' not in event.flags


def with_shot_onnet(event: Event) -> bool:
    return 'withshotonnet' in event.flags

def with_slotshot(event: Event) -> bool:
    return 'withslotshot' in event.flags

def with_shot_onnet_whistle(event: Event) -> bool:
    return 'withshotonnetwhistle' in event.flags

def whistle_before_exit(event: Event) -> bool:
    return 'whistlebeforeexit' in event.flags

def with_cycle_pass(event: Event) -> bool:
    return 'withcyclepass' in event.flags

def without_cycle_pass(event: Event) -> bool:
    return 'withcyclepass' not in event.flags

def with_no_shot(event: Event):
    return 'shot' not in ''.join(event.flags)

def east_of_dot(event: Event) -> bool:
    return 'eastofdot' in event.flags

def west_of_dot(event: Event) -> bool:
    return 'westofdot' in event.flags

def midice(event: Event) -> bool:
    return 'midice' in event.flags

def is_successful(event: Event) -> bool:
    return event.outcome == 'successful'

def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'

# def _successul(events: Iterable[Event]) -> Iterable[Event]:
#     return [e for e in events if e.outcome == 'successful']
#
# def _failed(events: Iterable[Event]) -> Iterable[Event]:
#     return [e for e in events if e.outcome == 'failed']


# --- Filter groups --------------------------------------------------------

Predicate = Callable[[Event], bool]

ENTRIES_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed ': is_failed,
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

    'Type': {
        'pass': is_pass,
        'carry': is_carry,
    },

    'Location': {
        'West of Dot': west_of_dot,
        'Mid-ice': midice,
        'East of Dot': east_of_dot,
    },

    'Cycle Pass': {
        'With Cycle Pass': with_cycle_pass,
        'Without Cycle Pass': without_cycle_pass,
    }

}

# --- Base sets ------------------------------------------------------------

def all_controlled_entries(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'controlledentry']
    return _for_team(events, team_id) if team_id else events


def entries_matching(entries: Iterable[Event], group: str, item: str) -> list[Event]:
    """Entries passing one named filter item."""
    try:
        predicate = ENTRIES_FILTERS[group][item]
    except KeyError:
        raise KeyError(f"unknown filter {group!r}/{item!r}; groups are "
                       f"{sorted(ENTRIES_FILTERS)}") from None
    return [e for e in entries if predicate(e)]


def filter_entries(entries: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_entries(shots, Result=['Successful'], Entry_Type=['Inner Slot'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    entries = list(entries)
    for raw_group, items in selections.items():
        group = raw_group.replace('_', ' ')
        if group not in ENTRIES_FILTERS:
            raise KeyError(f"unknown filter group {group!r}; "
                           f"groups are {sorted(ENTRIES_FILTERS)}")
        if isinstance(items, str):
            items = [items]
        predicates = [ENTRIES_FILTERS[group][i] for i in items]
        entries = [e for e in entries if any(p(e) for p in predicates)]
    return entries


def group_breakdown(entries: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given shots."""
    entries = list(entries)
    return {group: {item: [e for e in entries if predicate(e)]
                    for item, predicate in items.items()}
            for group, items in ENTRIES_FILTERS.items()}


def check_groups_exhaustive(entries: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every shot.

    The property the filter UI depends on: tick everything in a group and you
    get all the shots back.
    """
    entries = list(entries)
    out = {}
    for group, items in ENTRIES_FILTERS.items():
        covered = {id(e) for e in entries
                   if any(p(e) for p in items.values())}
        out[group] = len(covered) == len(entries)
    return out


# --- Helpers --------------------------------------------------------------

def _for_team(events: Iterable[Event], team_id: int) -> Iterable[Event]:
    return [e for e in events if e.team_id == int(team_id)]

def get_full_data(game: Game, raw_game: RawGame | None = None) -> dict:
    """raw_game is accepted for backwards compatibility and no longer used --
    play_section now comes off the Event directly."""
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        controlled_entries = all_controlled_entries(game, team_id)
        out = {'All Controlled Entries': controlled_entries}
        for group, items in group_breakdown(controlled_entries).items():
            for item, events in items.items():
                out[f'{group} - {item}'] = events
        res[team_id] = out
    return res

def print_res(res):
    for k in list(res.keys()):
        print(k)
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))

if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 191504
    GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    team_id=1397

    k = get_full_data(game)

    print_res(k)
    entries = all_controlled_entries(game) #, team_id)

    print("\nexhaustiveness:", check_groups_exhaustive(entries))
    print("Passes in game (both teams):",
          len(filter_entries(entries,
                           **{'Type': ['pass']})))
    # oz_carries = oz_carry(game)
    # oz_carries = _for_team(oz_carries, team_id)
    # print()
    # print('oz carries: ', len(oz_carries))
    # oz_carries = _successul(oz_carries)
    # print('successful carrries: ', len(oz_carries))
    # oz_carries = _whith_play_after(oz_carries)
    # print('carries with play after: ', len(oz_carries))
    #
    # oz_passes = oz_pass(game)
    # oz_passes = _for_team(oz_passes, team_id)
    # print('oz passes: ', len(oz_passes))
    # oz_passes = _successul(oz_passes)
    # print('successful passes: ', len(oz_passes))
    # oz_carries = _whith_play_after(oz_passes)
    # print('passes with play after: ', len(oz_carries))
    # exit(0)

