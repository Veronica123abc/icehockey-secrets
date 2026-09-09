#!/usr/bin/python
"""Passing metrics.

The supplier packs three things into a pass's ``type``: a base direction
("north", "d2d", "slot", ...), an optional "ozentry" PREFIX marking an entry
pass, and an optional "offboards" SUFFIX. So "ozentrystretchoffboards" is a
stretch entry pass played off the boards. :func:`pass_components` unpacks it,
and every filter here is built on that rather than on string matching.

Combined with ``Event.zone`` this reproduces exactly the thirteen pass types
in CLAUDE.md: across 12 games they account for 10103 of 10114 passes, the
remaining 11 being untyped ('none') passes the supplier never classified.

Two things the spec does not mention, both confirmed over 25 games:

* Pass outcome is NOT binary. Besides 'successful' (16229) and 'failed'
  (5045) there is 'undetermined' (21) -- so successful + failed does not
  exhaust the passes, and neither filter is the complement of the other.
  Nearly all of these are the same untyped passes counted by
  :func:`unclassified_passes`.
* Receptions in this data are only 'successful' or 'failed'.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game

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
    return _for_team(events, team_id) if team_id else events


def receptions(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'reception']
    return _for_team(events, team_id) if team_id else events


# --- Generic filters ------------------------------------------------------

def successful(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if e.outcome == 'successful']


def failed(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if e.outcome == 'failed']


def in_zone(events: Iterable[Event], zone: str) -> list[Event]:
    """zone is 'dz', 'nz' or 'oz'."""
    return [e for e in events if e.zone == zone]


def in_slot(events: Iterable[Event]) -> list[Event]:
    """Events located in the offensive-zone slot, by play_section."""
    return [e for e in events if e.play_section in OZ_SLOT_SECTIONS]


def entry_passes(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if pass_components(e)[1]]


def offboards_passes(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if pass_components(e)[2]]


def direct_passes(events: Iterable[Event]) -> list[Event]:
    """Passes not played off the boards."""
    return [e for e in events if not pass_components(e)[2]]


# --- The thirteen named pass types ---------------------------------------

def passes_of_type(game: Game, label: str, team_id: int | str | None = None) -> list[Event]:
    """One of the thirteen types in :data:`PASS_TYPES`, by label.

    Matches on (zone, base type, entry flag), so both the direct and the
    off-the-boards variant are included -- use :func:`direct_passes` or
    :func:`offboards_passes` to split them.
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


# --- Receptions -----------------------------------------------------------

def oz_entry_receptions(events: Iterable[Event]) -> list[Event]:
    """Receptions completing an OZ entry (type 'ozentry')."""
    return [e for e in events if e.type == 'ozentry']


def non_oz_entry_receptions(events: Iterable[Event]) -> list[Event]:
    """Every other reception (type 'regular')."""
    return [e for e in events if e.type != 'ozentry']


# --- Helpers --------------------------------------------------------------

def _for_team(events: Iterable[Event], team_id: int | str) -> list[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        team_passes = passes(game, team_id)
        team_receptions = receptions(game, team_id)
        breakdown = pass_type_breakdown(game, team_id)

        out = {
            'All passes': team_passes,
            'All passes - successful': successful(team_passes),
            'All passes - failed': failed(team_passes),
        }
        for zone in ('dz', 'nz', 'oz'):
            out[f'{zone.upper()} passes'] = in_zone(team_passes, zone)
        for label, events in breakdown.items():
            out[label] = events
            out[f'  {label} - successful'] = successful(events)
            out[f'  {label} - failed'] = failed(events)
        out['Unclassified passes'] = unclassified_passes(game, team_id)
        out['Entry passes'] = entry_passes(team_passes)
        out['Off-boards passes'] = offboards_passes(team_passes)
        out['Direct passes'] = direct_passes(team_passes)

        out['All receptions'] = team_receptions
        out['Receptions - successful'] = successful(team_receptions)
        out['Receptions - failed'] = failed(team_receptions)
        for zone in ('dz', 'nz', 'oz'):
            out[f'Receptions - {zone.upper()}'] = in_zone(team_receptions, zone)
        out['Receptions - slot'] = in_slot(team_receptions)
        out['Receptions - OZ entry'] = oz_entry_receptions(team_receptions)
        out['Receptions - not OZ entry'] = non_oz_entry_receptions(team_receptions)

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
