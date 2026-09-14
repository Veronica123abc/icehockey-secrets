#!/usr/bin/python
"""Defensive metrics.

Every metric here is credited to the DEFENDING team: for all of these events
``Event.team_id`` is the defender, not the team in possession (verified: 82/82
on controlledentryagainst). ``Event.zone`` is likewise relative to the credited
team, so opposition shots show up as ``dz`` events.

Unlike most of ``derive/``, these work on BOTH vocabularies: every event name
used here (controlledentryagainst, dumpinagainst, pressure, block, check,
receptionprevention) is present in ``playsequence.json`` as well as the
compiled file, and every count below is byte-identical from either source.

WHICH POPULATIONS GET A FILTER DICTIONARY. Three of the seven have internal
structure worth grouping, and do:

* ``controlledentryagainst`` -- :data:`ENTRY_AGAINST_FILTERS`
* ``block``                  -- :data:`BLOCK_FILTERS`
* ``check``                  -- :data:`CHECK_FILTERS`

The others are single-valued and so have nothing to filter on; giving them
groups would be decoration, not structure. Over games 186461 + 191848:

* ``dumpinagainst`` -- all 124 are type 'none', outcome 'undetermined', zone
  'dz'.
* ``pressure`` -- all 236 are type 'shot', outcome 'undetermined', zone 'dz'.
  This is the location record per opposition shot, NOT a filtered set of
  pressured shots; see :func:`pressured_shots_against` for the latter.
* ``receptionprevention`` -- 8 events, all type 'none' and successful; only
  zone varies.

Group exhaustiveness, verified over those two games. Entries against (136):
Result 57+79, and Differential Even 119 + Odd-Man 17 -- 'Breakaway' is a
SUBSET of 'Odd-Man' (1on0 satisfies n>m), the same deliberate overlap
shooting's 'Slot' has, and 'Untagged' covers a rush the supplier never
classified. Blocks (278): Type 176+70+32, Result 249+29, Zone 170+28+80.
Checks (86): Type 63+23, Zone 56+12+18. Checks carry no Result group because
SportLogIQ counts only checks that removed possession, so all 86 are
'successful'.

The group machinery itself lives in ``hockey.derive.filter_group``.
"""
from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.filter_group import FilterGroups, Predicate, for_team

_SETTINGS: Settings | None = None


def _settings() -> Settings:
    """Settings, resolved on first use rather than at import.

    Settings.from_env raises when DATA_ROOT_DIR is unset, and this module
    is imported by the game canvas through hockey.derive.metric_catalog.
    The canvas must keep working in db_only deployments, where that
    variable is deliberately absent -- so nothing here may touch the
    filesystem just to be imported.
    """
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings.from_env(project_root=Path(__file__).resolve().parent)
    return _SETTINGS

# Entries against carry the DZ player differential in ``type``, spelled
# "<attackers>on<defenders>" -- 3on3, 2on1, 1on0. Observed across 40 games:
# 3on3, 1on2, 2on2, 2on3, 1on1, 3on2, 2on1, 1on0, 3on1.
_DIFFERENTIAL_RE = re.compile(r"^(\d+)on(\d+)$")


def player_differential(event: Event) -> tuple[int, int] | None:
    """(attackers, defenders) in the DZ at the entry, or None if not tagged.

    None means the supplier did not classify the rush, not 0on0 -- callers
    must not fold it into any bucket. The 'Untagged' filter item is how the
    Differential group stays exhaustive without doing so.
    """
    match = _DIFFERENTIAL_RE.match(event.type or "")
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_denied(event: Event) -> bool:
    """The defender came out on top.

    ``controlledentryagainst`` fires only on successful opposition entries, so
    its outcome cannot be describing whether the entry worked (it would be
    uniformly 'successful'). It is the DEFENDER's result: 'successful' means
    the opposition lost possession before entering or on the first play after
    the entry, which is exactly SportLogIQ's denial definition.
    """
    return event.outcome == 'successful'


def is_not_denied(event: Event) -> bool:
    return event.outcome == 'failed'


def is_even_differential(event: Event) -> bool:
    """Defence not outnumbered (m >= n)."""
    diff = player_differential(event)
    return diff is not None and diff[1] >= diff[0]


def is_odd_man_differential(event: Event) -> bool:
    """Attack outnumbers the defence (n > m). Includes breakaways."""
    diff = player_differential(event)
    return diff is not None and diff[0] > diff[1]


def is_breakaway(event: Event) -> bool:
    """A clean breakaway (1on0). A SUBSET of odd-man, not a sibling."""
    diff = player_differential(event)
    return diff is not None and diff[0] == 1 and diff[1] == 0


def is_untagged_differential(event: Event) -> bool:
    """The supplier did not classify the rush."""
    return player_differential(event) is None


def is_successful(event: Event) -> bool:
    return event.outcome == 'successful'


def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'


def is_pass_block(event: Event) -> bool:
    return event.type == 'pass'


def is_shot_block(event: Event) -> bool:
    return event.type == 'shot'


def is_blueline_block(event: Event) -> bool:
    """Blocked dump-out / NZ pass keeping the puck in the OZ. The one metric
    here credited to the ATTACKING team's player holding the line, hence zone
    'oz'; every one observed is successful."""
    return event.type == 'blueline'


def is_body_check(event: Event) -> bool:
    return event.type == 'body'


def is_stick_check(event: Event) -> bool:
    return event.type == 'stick'


def in_dz(event: Event) -> bool:
    return event.zone == 'dz'


def in_nz(event: Event) -> bool:
    return event.zone == 'nz'


def in_oz(event: Event) -> bool:
    return event.zone == 'oz'


# --- Filter groups --------------------------------------------------------

ENTRY_AGAINST_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Denied': is_denied,
        'Not Denied': is_not_denied,
    },
    'Differential': {
        'Even': is_even_differential,
        'Odd-Man': is_odd_man_differential,
        'Breakaway': is_breakaway,
        'Untagged': is_untagged_differential,
    },
}

BLOCK_FILTERS: dict[str, dict[str, Predicate]] = {
    'Type': {
        'Pass': is_pass_block,
        'Shot': is_shot_block,
        'Blueline': is_blueline_block,
    },
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

CHECK_FILTERS: dict[str, dict[str, Predicate]] = {
    'Type': {
        'Body': is_body_check,
        'Stick': is_stick_check,
    },
    'Zone': {
        'DZ': in_dz,
        'NZ': in_nz,
        'OZ': in_oz,
    },
}

ENTRIES_AGAINST = FilterGroups('controlledentryagainst', ENTRY_AGAINST_FILTERS)
BLOCKS = FilterGroups('block', BLOCK_FILTERS)
CHECKS = FilterGroups('check', CHECK_FILTERS)


# --- Base sets ------------------------------------------------------------

def all_entries_against(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Controlled entries conceded, one per SUCCESSFUL opposition entry.

    Verified on two games, all four team-pairs: the count for a team equals
    the opponent's count of ``controlledentry`` with outcome 'successful'
    exactly (48/48, 34/34, 36/36, 31/31). Denied attempts do not produce an
    event here -- they are not entries.
    """
    events = [e for e in game.events if e.name == 'controlledentryagainst']
    return for_team(events, team_id) if team_id else events


def all_blocks(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'block']
    return for_team(events, team_id) if team_id else events


def all_checks(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'check']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def entries_against_matching(entries: Iterable[Event], group: str, item: str) -> list[Event]:
    """Entries against passing one named filter item."""
    return ENTRIES_AGAINST.matching(entries, group, item)


def filter_entries_against(entries: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_entries_against(entries, Result=['Not Denied'],
                               Differential=['Odd-Man'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return ENTRIES_AGAINST.filter(entries, **selections)


def group_breakdown(entries: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given entries against."""
    return ENTRIES_AGAINST.breakdown(entries)


def check_groups_exhaustive(entries: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every entry against."""
    return ENTRIES_AGAINST.check_exhaustive(entries)


def blocks_matching(blocks: Iterable[Event], group: str, item: str) -> list[Event]:
    return BLOCKS.matching(blocks, group, item)


def filter_blocks(blocks: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    return BLOCKS.filter(blocks, **selections)


def block_group_breakdown(blocks: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    return BLOCKS.breakdown(blocks)


def check_block_groups_exhaustive(blocks: Iterable[Event]) -> dict[str, bool]:
    return BLOCKS.check_exhaustive(blocks)


def checks_matching(checks: Iterable[Event], group: str, item: str) -> list[Event]:
    return CHECKS.matching(checks, group, item)


def filter_checks(checks: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    return CHECKS.filter(checks, **selections)


def check_group_breakdown(checks: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    return CHECKS.breakdown(checks)


def check_checks_groups_exhaustive(checks: Iterable[Event]) -> dict[str, bool]:
    return CHECKS.check_exhaustive(checks)


# --- Populations with nothing to filter on -------------------------------

def dumpins_against(game: Game) -> Iterable[Event]:
    """Dump-ins conceded, crediting the closest defender in the lane.

    Fewer than the opponent's dump-ins (26 vs 36, 32 vs 38, 18 vs 23, 21 vs
    26 across the two sample games) because the definition requires a defender
    *in the lane* -- dump-ins with nobody in the lane are not credited.
    """
    return [e for e in game.events if e.name == 'dumpinagainst']


def shot_pressure(game: Game) -> Iterable[Event]:
    """One record per opposition shot, crediting the closest defender.

    ``pressure`` events match the opponent's shot count exactly (67/67, 47/47,
    60/60, 34/34), are always type 'shot', and carry the defender's location in
    ``x_adj_coord``/``y_adj_coord``. They are the location record the
    definition describes, NOT a filtered set of pressured shots -- for that
    see :func:`pressured_shots_against`.
    """
    return [e for e in game.events if e.name == 'pressure']


def pressured_shots_against(game: Game) -> Iterable[Event]:
    """Opposition shots that actually met the pressure distance criterion.

    The 8-foot/3-foot test is not recomputed here -- the supplier already
    applies it and marks the shot with the 'withpressure' flag. These are
    shot events, so they belong to the SHOOTING team; use
    :func:`shot_pressure` when you want events credited to the defender.
    """
    return [e for e in game.events if e.name == 'shot' and 'withpressure' in e.flags]


def reception_preventions(game: Game) -> Iterable[Event]:
    """Pass prevented by making contact with the intended receiver."""
    return [e for e in game.events if e.name == 'receptionprevention']


# --- Named sets kept for existing callers ---------------------------------

def controlled_entries_against(game: Game) -> Iterable[Event]:
    return all_entries_against(game)


def entry_denials(game: Game) -> Iterable[Event]:
    """DZ entry denials. Equivalent to Result=['Denied']."""
    return [e for e in all_entries_against(game) if is_denied(e)]


def failed_entries_against(game: Game) -> Iterable[Event]:
    """Entries against the defender did NOT deny -- the complement of
    :func:`entry_denials`."""
    return [e for e in all_entries_against(game) if is_not_denied(e)]


def even_entries_against(game: Game) -> Iterable[Event]:
    """NOT-DENIED entries against with the defence not outnumbered.

    Note the Result constraint: these are the not-denied subset, not the whole
    Differential group. Equivalent to
    ``filter_entries_against(.., Result=['Not Denied'], Differential=['Even'])``.
    """
    return filter_entries_against(all_entries_against(game),
                                  Result=['Not Denied'], Differential=['Even'])


def odd_man_entries_against(game: Game) -> Iterable[Event]:
    """Not-denied entries against with the attack outnumbering the defence.

    Breakaways satisfy this too, so :func:`breakaway_entries_against` is a
    SUBSET of this, not a sibling bucket.
    """
    return filter_entries_against(all_entries_against(game),
                                  Result=['Not Denied'], Differential=['Odd-Man'])


def breakaway_entries_against(game: Game) -> Iterable[Event]:
    """Not-denied entries against on a clean breakaway (1on0)."""
    return filter_entries_against(all_entries_against(game),
                                  Result=['Not Denied'], Differential=['Breakaway'])


def blocked_passes(game: Game) -> Iterable[Event]:
    """Opposition pass attempts stopped by a stick or body."""
    return filter_blocks(all_blocks(game), Type=['Pass'], Result=['Successful'])


def failed_blocked_passes(game: Game) -> Iterable[Event]:
    """Pass touched on the way to the receiver but still completed."""
    return filter_blocks(all_blocks(game), Type=['Pass'], Result=['Failed'])


def blocked_shots(game: Game) -> Iterable[Event]:
    """Opposition shot attempts stopped before reaching the net."""
    return filter_blocks(all_blocks(game), Type=['Shot'], Result=['Successful'])


def failed_blocked_shots(game: Game) -> Iterable[Event]:
    """Shot touched on the way but still reaching the net."""
    return filter_blocks(all_blocks(game), Type=['Shot'], Result=['Failed'])


def blueline_holds(game: Game) -> Iterable[Event]:
    """Blocked dump-out / NZ pass that keeps the puck in the OZ."""
    return [e for e in all_blocks(game) if is_blueline_block(e)]


def body_checks(game: Game) -> Iterable[Event]:
    """Body checks that removed possession (the only kind SL counts)."""
    return [e for e in all_checks(game) if is_body_check(e)]


def stick_checks(game: Game) -> Iterable[Event]:
    """Stick checks separating the puck from an opponent."""
    return [e for e in all_checks(game) if is_stick_check(e)]


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def _conceded_by(events: Iterable[Event], team_id: int) -> list[Event]:
    """Events belonging to the OTHER team -- for metrics carried on the
    opposition's own event (a shot), credited to the team defending it."""
    return [e for e in events if e.team_id is not None and e.team_id != int(team_id)]


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        entries = all_entries_against(game, team_id)
        blocks = all_blocks(game, team_id)
        checks = all_checks(game, team_id)

        res[team_id] = {
            'All Entries Against': entries,
            **ENTRIES_AGAINST.rows(entries),
            # The differential within the entries that were NOT denied -- the
            # AND of two groups, which no single group row expresses.
            'Not Denied - Even': filter_entries_against(
                entries, Result=['Not Denied'], Differential=['Even']),
            'Not Denied - Odd-Man': filter_entries_against(
                entries, Result=['Not Denied'], Differential=['Odd-Man']),
            'Not Denied - Breakaway': filter_entries_against(
                entries, Result=['Not Denied'], Differential=['Breakaway']),

            'All Blocks': blocks,
            **BLOCKS.rows(blocks, 'Block '),

            'All Checks': checks,
            **CHECKS.rows(checks, 'Check '),

            # Populations with no internal structure to group on.
            'Dump-Ins Against': for_team(dumpins_against(game), team_id),
            'Shot Pressure': for_team(shot_pressure(game), team_id),
            'Reception Preventions': for_team(reception_preventions(game), team_id),
            # Rides on the opposition's own shot event, so credited inversely.
            'Pressured Shots Against': _conceded_by(
                pressured_shots_against(game), team_id),
        }
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDEFENSIVE STATS FOR {k}")
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

    entries = all_entries_against(game)
    print("\nentries-against exhaustiveness:", check_groups_exhaustive(entries))
    print("block exhaustiveness:", check_block_groups_exhaustive(all_blocks(game)))
    print("check exhaustiveness:", check_checks_groups_exhaustive(all_checks(game)))
    print("odd-man entries the defender did not deny:",
          len(filter_entries_against(entries, Result=['Not Denied'],
                                     Differential=['Odd-Man'])))
