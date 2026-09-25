#!/usr/bin/python
"""Dump-in metrics.

Three populations live here, each with its own filter dictionary:

* ``dumpin`` -- the puck event, one per attempt. Carries the dumping player's
  location ('westofdot', 'midice', 'eastofdot') and the technique ('rim',
  'crossice', 'soft', 'straight') in flags, and dump-vs-chip in ``type``.
* ``dumpinentry`` -- 1:1 with ``dumpin``, and the event whose OUTCOME says
  whether the dumping team got the puck back.
* ``dumpinrecovery`` -- who picked the puck up afterwards, and what came of
  it. ``type`` is a concatenation: an 'offensive'/'defensive' prefix (the
  dumping team vs the opposition), optionally 'selfchipin', then the same
  withplay/withshotonnet/withslotshot decorations that appear in flags.

WHY ``dumpinentry`` IS ITS OWN POPULATION and not a decoration on ``dumpin``:
a dump-in's own 'successful' is a DEPTH criterion (see CLAUDE.md -- probably
past the last defender), while a dumpinentry's is possession. Over games
186449 + 186461 + 191848 the successful entries number 83 and the offensive
dump-in recoveries also number 83 -- per game 25, 34, 24 either way -- so
"successful entry" means "the dumping team recovered", and it is the only
population here whose share of the whole is a recovery RATE. Rating recoveries
against ``Dump-ins · Successful`` instead answers a different question and is
not bounded by 1.

Group exhaustiveness for ``dumpin``, verified over games 186461 + 191848 (150
dump-ins): Type 129+21, Location 65+31+54 and Result 122+28 each total 150
exactly. Technique covers only 122 -- 28 attempts carry no technique flag --
so that group has an explicit 'Untagged' item to keep it exhaustive.

For ``dumpinentry``, verified over 186449 + 186461 + 191848 on the FILE path
(209 entries, 1:1 with 209 dump-ins, all 209 linked by base_event_id; 191848
is not in the database, so a database-only check sees only two of the three):
Result 83+126 = 209, and With Shot covers all 209 (on-net 26 and slot 17 union
to 32, plus 177 with no shot). The two shot items overlap deliberately, as
they do in shooting's 'Slot'. It is given no Technique group even though it
carries those flags: they are identical to the paired dump-in's on all 209
pairs, so the axis already exists as ``Dump-ins · Technique`` and a second
copy would drift.

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

#: The entry's Result is possession, not depth: successful means the dumping
#: team recovered. The shot decorations are the same flags the recovery
#: population carries, so the predicates are shared rather than restated.
DUMPIN_ENTRY_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'With Shot': {
        'With Shot On Net': with_shot_onnet,
        'With Slot Shot': with_slotshot,
        'With No Shot': with_no_shot,
    },
}

DUMPINS = FilterGroups('dumpin', DUMPIN_FILTERS, 'Dump-ins')
DUMPIN_ENTRIES = FilterGroups('dumpinentry', DUMPIN_ENTRY_FILTERS, 'Dump-in entries')
RECOVERIES = FilterGroups('dumpinrecovery', DUMPIN_RECOVERY_FILTERS, 'Dump-in recoveries')


# --- Base sets ------------------------------------------------------------

def all_dumpins(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every dump-in attempt, one per puck event."""
    events = [e for e in game.events if e.name == 'dumpin']
    return for_team(events, team_id) if team_id else events


def all_dumpin_entries(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every dump-in entry -- one per dump-in, successful iff recovered."""
    events = [e for e in game.events if e.name == 'dumpinentry']
    return for_team(events, team_id) if team_id else events


def all_dumpin_recoveries(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every dump-in recovery, by either team."""
    events = [e for e in game.events if e.name == 'dumpinrecovery']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def filter_dumpins(dumpins: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_dumpins(dumpins, Result=['Successful'], Type=['Chip'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return DUMPINS.filter(dumpins, **selections)


def check_groups_exhaustive(dumpins: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every dump-in."""
    return DUMPINS.check_exhaustive(dumpins)


def check_entry_groups_exhaustive(entries: Iterable[Event]) -> dict[str, bool]:
    return DUMPIN_ENTRIES.check_exhaustive(entries)


def check_recovery_groups_exhaustive(recoveries: Iterable[Event]) -> dict[str, bool]:
    return RECOVERIES.check_exhaustive(recoveries)


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

_for_team = for_team


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        dumpins = all_dumpins(game, team_id)
        entries = all_dumpin_entries(game, team_id)
        recoveries = all_dumpin_recoveries(game, team_id)
        res[team_id] = {
            **DUMPINS.rows(dumpins),
            **DUMPIN_ENTRIES.rows(entries),
            **RECOVERIES.rows(recoveries),
        }
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDUMP-IN STATS FOR {k}")
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

    dumpins = all_dumpins(game)
    print("\nexhaustiveness:", check_groups_exhaustive(dumpins))
    print("recovery exhaustiveness:",
          check_recovery_groups_exhaustive(all_dumpin_recoveries(game)))
    print("successful chips:",
          len(filter_dumpins(dumpins, Type=['Chip'], Result=['Successful'])))
