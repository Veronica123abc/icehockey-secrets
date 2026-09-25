#!/usr/bin/python
"""Controlled entry metrics.

A ``controlledentry`` is an entry into the OZ with possession. Every one is
zone 'oz' and outcome successful or failed -- there is no third outcome.

WHERE EACH ATTRIBUTE LIVES. The supplier is not consistent about type versus
flags, so each predicate below reads whichever actually carries the value
(counts over games 186461 + 191848, 141 entries):

* 'withplay' is in the TYPE ('carrywithplay'), 79 of 141 -- but the matching
  ``withplayafter`` FLAG is on the same 79 entries, so the flag is used.
* ``withshotonnet`` agrees in both places (56 and 56).
* ``withslotshot`` does NOT: the type spells it 'withshotonnetandslotshot', so
  substring-matching the type finds only 8 of the 35 the flag marks. The flag
  is the correct source.
* 'carry' / 'pass' are a TYPE prefix and appear in no flag.

Group exhaustiveness, verified over those same two games: Result 136+5, With
Play After 79+62, Type 121+20, Location 48+41+52 and Cycle Pass 54+87 each
total 141 exactly. With Shot totals 168 because 'With Shot On Net' and 'With
Slot Shot' deliberately overlap -- coverage is still all 141, the same
convention as shooting's 'Slot'.

One nuance the Cycle Pass group hides: 41 entries carry ``withfailedcyclepass``
and land under 'Without Cycle Pass', which is accurate (no cycle pass was
completed) but is not the same as no cycle pass having been attempted.
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


def is_pass(event: Event) -> bool:
    return 'pass' in (event.type or '')


def is_carry(event: Event) -> bool:
    return 'carry' in (event.type or '')


def with_play_after(event: Event) -> bool:
    return 'withplayafter' in event.flags


def without_play_after(event: Event) -> bool:
    return 'withplayafter' not in event.flags


def with_shot_onnet(event: Event) -> bool:
    return 'withshotonnet' in event.flags


def with_slotshot(event: Event) -> bool:
    """From the FLAG: the type spells this 'withshotonnetandslotshot' and so
    matches only 8 of the 35 entries the flag marks."""
    return 'withslotshot' in event.flags


def with_no_shot(event: Event) -> bool:
    """Neither shot flag -- the complement that makes 'With Shot' exhaustive."""
    return 'shot' not in ''.join(event.flags)


def with_shot_onnet_whistle(event: Event) -> bool:
    return 'withshotonnetwhistle' in event.flags


def whistle_before_exit(event: Event) -> bool:
    return 'whistlebeforeexit' in event.flags


def west_of_dot(event: Event) -> bool:
    return 'westofdot' in event.flags


def midice(event: Event) -> bool:
    return 'midice' in event.flags


def east_of_dot(event: Event) -> bool:
    return 'eastofdot' in event.flags


def with_cycle_pass(event: Event) -> bool:
    return 'withcyclepass' in event.flags


def without_cycle_pass(event: Event) -> bool:
    return 'withcyclepass' not in event.flags


def with_failed_cycle_pass(event: Event) -> bool:
    """A cycle pass was attempted and not completed. A SUBSET of 'Without
    Cycle Pass', not a sibling -- exposed as a function, not a filter item."""
    return 'withfailedcyclepass' in event.flags


# --- Filter groups --------------------------------------------------------

ENTRIES_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
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
        'Pass': is_pass,
        'Carry': is_carry,
    },
    'Location': {
        'West of Dot': west_of_dot,
        'Mid-Ice': midice,
        'East of Dot': east_of_dot,
    },
    'Cycle Pass': {
        'With Cycle Pass': with_cycle_pass,
        'Without Cycle Pass': without_cycle_pass,
    },
}

ENTRIES = FilterGroups('controlledentry', ENTRIES_FILTERS, 'Controlled entries')


# --- Base sets ------------------------------------------------------------

def all_controlled_entries(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'controlledentry']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def filter_entries(entries: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_entries(entries, Result=['Successful'], Type=['Carry'])
    """
    return ENTRIES.filter(entries, **selections)


def check_groups_exhaustive(entries: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every entry."""
    return ENTRIES.check_exhaustive(entries)


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game, raw_game: RawGame | None = None) -> dict:
    """raw_game is accepted for backwards compatibility and no longer used --
    play_section now comes off the Event directly."""
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        entries = all_controlled_entries(game, team_id)
        res[team_id] = ENTRIES.rows(entries)
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nCONTROLLED ENTRY STATS FOR {k}")
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

    entries = all_controlled_entries(game)
    print("\nexhaustiveness:", check_groups_exhaustive(entries))
    print("carries with play after:",
          len(filter_entries(entries, Type=['Carry'],
                             With_Play_After=['With Play After'])))
