#!/usr/bin/python
"""Passing metrics.

The supplier packs three things into a pass's ``type``: a base direction
("north", "d2d", "slot", ...), an optional "ozentry" PREFIX marking an entry
pass, and an optional "offboards" SUFFIX. So "ozentrystretchoffboards" is a
stretch entry pass played off the boards. :func:`pass_components` unpacks it,
and every filter here is built on that rather than on string matching.

Two populations, each with its own filter dictionary: ``pass`` and
``reception``. On top of the pass groups, :data:`PASS_TYPES` names the
thirteen zone x type combinations from CLAUDE.md; those are a cross-product of
two groups rather than a group of their own, so they stay a separate lookup.

Two things the spec does not mention, both confirmed over 25 games:

* Pass outcome is NOT binary. Besides 'successful' and 'failed' there is
  'undetermined' -- so successful + failed does not exhaust the passes, and
  neither filter is the complement of the other. 'Undetermined' is therefore
  an item in the Outcome group rather than an omission.
* Receptions in this data are only 'successful' or 'failed'.

Group exhaustiveness, verified over games 186461 + 191848 (1746 passes, 1394
receptions): Outcome 1368+376+2, Zone 657+190+899 and the nine base Types
(291+82+283+405+356+141+140+30+18) each total 1746; Delivery and Entry are
exhaustive by construction. Reception Outcome 1368+26, Zone 447+228+719 and
Type 16+1378 each total 1394.

The group machinery itself lives in ``hockey.derive.filter_group``.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.filter_group import FilterGroups, Predicate, for_team

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

_ENTRY_PREFIX = 'ozentry'
_OFFBOARDS_SUFFIX = 'offboards'

# The offensive-zone slot, as sectioned by the supplier. Same three sections
# used in playmaking.metrics -- the DZ twins are the defensive-zone mirror.
OZ_SLOT_SECTIONS = frozenset({'innerSlot', 'eastOuterSlot', 'westOuterSlot'})


def pass_components(event: Event) -> tuple[str, bool, bool]:
    """Unpack a pass type into (base_type, is_entry, is_offboards).

    "ozentrystretchoffboards" -> ("stretch", True, True)
    "d2doffboards"            -> ("d2d",     False, True)
    "ozentry"                 -> ("",        True,  False)   # plain NZ entry
    """
    kind = event.type or ''
    is_entry = kind.startswith(_ENTRY_PREFIX)
    if is_entry:
        kind = kind[len(_ENTRY_PREFIX):]
    is_offboards = kind.endswith(_OFFBOARDS_SUFFIX)
    if is_offboards:
        kind = kind[:-len(_OFFBOARDS_SUFFIX)]
    return kind, is_entry, is_offboards


def _base_kind(event: Event) -> str:
    return pass_components(event)[0]


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_successful(event: Event) -> bool:
    return event.outcome == 'successful'


def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'


def is_undetermined(event: Event) -> bool:
    """Neither successful nor failed -- rare, and almost always an untyped
    pass the supplier never classified."""
    return event.outcome not in ('successful', 'failed')


def in_dz(event: Event) -> bool:
    return event.zone == 'dz'


def in_nz(event: Event) -> bool:
    return event.zone == 'nz'


def in_oz(event: Event) -> bool:
    return event.zone == 'oz'


# Base direction. Matched on the unpacked base type, so each of these covers
# both the direct and the off-the-boards spelling.
def is_outlet(event: Event) -> bool:
    return _base_kind(event) == 'outlet'


def is_stretch(event: Event) -> bool:
    return _base_kind(event) == 'stretch'


def is_d2d(event: Event) -> bool:
    return _base_kind(event) == 'd2d'


def is_north(event: Event) -> bool:
    return _base_kind(event) == 'north'


def is_south(event: Event) -> bool:
    return _base_kind(event) == 'south'


def is_eastwest(event: Event) -> bool:
    return _base_kind(event) == 'eastwest'


def is_off_the_rush(event: Event) -> bool:
    return _base_kind(event) == 'rush'


def is_to_the_slot(event: Event) -> bool:
    return _base_kind(event) == 'slot'


def is_untyped(event: Event) -> bool:
    """No base direction: a bare entry pass, or one the supplier left 'none'.
    Keeps the Type group exhaustive."""
    return _base_kind(event) in ('', 'none')


def is_entry_pass(event: Event) -> bool:
    return pass_components(event)[1]


def is_not_entry_pass(event: Event) -> bool:
    return not is_entry_pass(event)


def is_offboards(event: Event) -> bool:
    return pass_components(event)[2]


def is_direct(event: Event) -> bool:
    """Not played off the boards."""
    return not is_offboards(event)


# --- Reception predicates -------------------------------------------------

def is_oz_entry_reception(event: Event) -> bool:
    return event.type == 'ozentry'


def is_not_oz_entry_reception(event: Event) -> bool:
    return event.type != 'ozentry'


def is_in_slot(event: Event) -> bool:
    """In the offensive-zone slot, by play_section."""
    return event.play_section in OZ_SLOT_SECTIONS


def is_not_in_slot(event: Event) -> bool:
    return not is_in_slot(event)


# --- Filter groups --------------------------------------------------------

PASS_FILTERS: dict[str, dict[str, Predicate]] = {
    'Outcome': {
        'Successful': is_successful,
        'Failed': is_failed,
        'Undetermined': is_undetermined,
    },
    'Zone': {
        'DZ': in_dz,
        'NZ': in_nz,
        'OZ': in_oz,
    },
    'Type': {
        'Outlet': is_outlet,
        'Stretch': is_stretch,
        'D2D': is_d2d,
        'North': is_north,
        'South': is_south,
        'East-West': is_eastwest,
        'Off the Rush': is_off_the_rush,
        'Slot': is_to_the_slot,
        'Untyped': is_untyped,
    },
    'Entry': {
        'Entry Pass': is_entry_pass,
        'Not Entry Pass': is_not_entry_pass,
    },
    'Delivery': {
        'Off the Boards': is_offboards,
        'Direct': is_direct,
    },
}

RECEPTION_FILTERS: dict[str, dict[str, Predicate]] = {
    'Outcome': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Zone': {
        'DZ': in_dz,
        'NZ': in_nz,
        'OZ': in_oz,
    },
    'Type': {
        'OZ Entry': is_oz_entry_reception,
        'Not OZ Entry': is_not_oz_entry_reception,
    },
    'Location': {
        'Slot': is_in_slot,
        'Not Slot': is_not_in_slot,
    },
}

PASSES = FilterGroups('pass', PASS_FILTERS)
RECEPTIONS = FilterGroups('reception', RECEPTION_FILTERS)


# label -> (zone, base_type, is_entry), in CLAUDE.md order.
PASS_TYPES: dict[str, tuple[str, str, bool]] = {
    'DZ D2D pass':             ('dz', 'd2d',      False),
    'DZ outlet pass':          ('dz', 'outlet',   False),
    'DZ stretch pass':         ('dz', 'stretch',  False),
    'DZ stretch entry pass':   ('dz', 'stretch',  True),
    'NZ south pass':           ('nz', 'south',    False),
    'NZ north pass':           ('nz', 'north',    False),
    'NZ east-west pass':       ('nz', 'eastwest', False),
    'NZ entry pass':           ('nz', '',         True),
    'OZ pass off the rush':    ('oz', 'rush',     False),
    'OZ south cycle pass':     ('oz', 'south',    False),
    'OZ north cycle pass':     ('oz', 'north',    False),
    'OZ east-west point pass': ('oz', 'eastwest', False),
    'OZ pass to the slot':     ('oz', 'slot',     False),
}


# --- Base sets ------------------------------------------------------------

def passes(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'pass']
    return for_team(events, team_id) if team_id else events


def receptions(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'reception']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def passes_matching(events: Iterable[Event], group: str, item: str) -> list[Event]:
    """Passes passing one named filter item."""
    return PASSES.matching(events, group, item)


def filter_passes(events: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_passes(passes, Outcome=['Successful'], Zone=['OZ'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return PASSES.filter(events, **selections)


def group_breakdown(events: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given passes."""
    return PASSES.breakdown(events)


def check_groups_exhaustive(events: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every pass."""
    return PASSES.check_exhaustive(events)


def receptions_matching(events: Iterable[Event], group: str, item: str) -> list[Event]:
    return RECEPTIONS.matching(events, group, item)


def filter_receptions(events: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    return RECEPTIONS.filter(events, **selections)


def reception_group_breakdown(events: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    return RECEPTIONS.breakdown(events)


def check_reception_groups_exhaustive(events: Iterable[Event]) -> dict[str, bool]:
    return RECEPTIONS.check_exhaustive(events)


# --- The thirteen named pass types ---------------------------------------

def passes_of_type(game: Game, label: str, team_id: int | str | None = None) -> list[Event]:
    """One of the thirteen types in :data:`PASS_TYPES`, by label.

    Matches on (zone, base type, entry flag), so both the direct and the
    off-the-boards variant are included -- use the Delivery group to split
    them.
    """
    try:
        zone, base, is_entry = PASS_TYPES[label]
    except KeyError:
        raise KeyError(f"unknown pass type {label!r}; expected one of "
                       f"{sorted(PASS_TYPES)}") from None
    out = []
    for e in passes(game, team_id):
        if e.zone != zone:
            continue
        kind, entry, _ = pass_components(e)
        if kind == base and entry == is_entry:
            out.append(e)
    return out


def pass_type_breakdown(game: Game, team_id: int | str | None = None) -> dict[str, list[Event]]:
    """All thirteen types at once, in CLAUDE.md order."""
    return {label: passes_of_type(game, label, team_id) for label in PASS_TYPES}


def unclassified_passes(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Passes none of the thirteen types claim -- the supplier's 'none' types."""
    claimed = {id(e) for evs in pass_type_breakdown(game, team_id).values() for e in evs}
    return [e for e in passes(game, team_id) if id(e) not in claimed]


# --- Named sets kept for existing callers ---------------------------------

def successful(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_successful(e)]


def failed(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_failed(e)]


def in_zone(events: Iterable[Event], zone: str) -> list[Event]:
    """zone is 'dz', 'nz' or 'oz'."""
    return [e for e in events if e.zone == zone]


def in_slot(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_in_slot(e)]


def entry_passes(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_entry_pass(e)]


def offboards_passes(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_offboards(e)]


def direct_passes(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_direct(e)]


def oz_entry_receptions(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_oz_entry_reception(e)]


def non_oz_entry_receptions(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if is_not_oz_entry_reception(e)]


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        team_passes = passes(game, team_id)
        team_receptions = receptions(game, team_id)

        out = {'All Passes': team_passes, **PASSES.rows(team_passes)}

        # The thirteen zone x type combinations, which are a cross-product of
        # two groups rather than a group of their own.
        for label, events in pass_type_breakdown(game, team_id).items():
            out[label] = events
            out[f'  {label} - successful'] = successful(events)
            out[f'  {label} - failed'] = failed(events)
        out['Unclassified passes'] = unclassified_passes(game, team_id)

        out['All Receptions'] = team_receptions
        out.update(RECEPTIONS.rows(team_receptions, 'Reception '))

        res[team_id] = out
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nPASSING STATS FOR {k}")
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

    team_passes = passes(game)
    print("\nexhaustiveness:", check_groups_exhaustive(team_passes))
    print("reception exhaustiveness:",
          check_reception_groups_exhaustive(receptions(game)))
    print("successful OZ slot passes:",
          len(filter_passes(team_passes, Outcome=['Successful'], Zone=['OZ'],
                            Type=['Slot'])))
