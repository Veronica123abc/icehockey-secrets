#!/usr/bin/python
"""Shooting metrics.

Shots are described by six independent filter GROUPS (see CLAUDE.md). Each
group is exhaustive: selecting every item in a group returns every shot. Two
groups contain deliberate overlap, so exhaustive does not mean disjoint --

* Result -- 'Led to Goal' is a subset of 'On Net', following the usual hockey
  convention that shots on net include goals. Use
  :func:`is_on_net_excluding_goals` if you need the four to partition.
* Shot Location -- 'Slot' is the union of 'Inner Slot' and 'Outer Slot'.

Every other group is a true binary partition.

Verified over 15 games / 1657 shots: the Result union and the Location union
each cover all shots exactly, ``'slot' in type`` agrees with the slot
play_sections on every shot (679/679), blocked shots always have outcome
'failed', goals always 'successful', and no shot carries an outcome other
than successful/failed.

The group machinery itself lives in ``hockey.derive.filter_group``.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.normalize.build_game_db import build_game_from_db
from hockey.model.game import Game
from hockey.db.database import open_database_azure
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

INNER_SLOT_SECTION = 'innerSlot'
OUTER_SLOT_SECTIONS = frozenset({'eastOuterSlot', 'westOuterSlot'})


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_goal(event: Event) -> bool:
    """Shot that scored. The 'goal' event is separate and shares no id."""
    return 'withgoal' in event.flags


def is_on_net(event: Event) -> bool:
    """Reached the net. Includes goals, as shots-on-net conventionally does."""
    return event.outcome == 'successful'


def is_on_net_excluding_goals(event: Event) -> bool:
    """On net but not scored -- use to make Result a strict partition."""
    return is_on_net(event) and not is_goal(event)


def is_blocked(event: Event) -> bool:
    return 'blocked' in event.type


def is_missed(event: Event) -> bool:
    """Missed the net: failed, but not blocked."""
    return not is_blocked(event) and event.outcome == 'failed'


def is_screened(event: Event) -> bool:
    return 'screened' in event.flags


def is_not_screened(event: Event) -> bool:
    return not is_screened(event)


def is_deflected(event: Event) -> bool:
    return 'deflected' in event.flags


def is_not_deflected(event: Event) -> bool:
    return not is_deflected(event)


def is_one_timer(event: Event) -> bool:
    return '1timer' in event.flags


def is_not_one_timer(event: Event) -> bool:
    return not is_one_timer(event)


def is_inner_slot(event: Event) -> bool:
    """Inner slot, by play_section -- the shot type only says 'slot'."""
    return event.play_section == INNER_SLOT_SECTION


def is_outer_slot(event: Event) -> bool:
    return event.play_section in OUTER_SLOT_SECTIONS


def is_slot(event: Event) -> bool:
    """Inner or outer slot. Equivalent to 'slot' in type on every shot seen."""
    return is_inner_slot(event) or is_outer_slot(event)


def is_outside(event: Event) -> bool:
    return not is_slot(event)


def is_pressured(event: Event) -> bool:
    return 'withpressure' in event.flags


def is_not_pressured(event: Event) -> bool:
    return not is_pressured(event)


# --- Filter groups --------------------------------------------------------

SHOT_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result': {
        'Led to Goal': is_goal,
        'On Net': is_on_net,
        'Blocked': is_blocked,
        'Missed': is_missed,
    },
    'Screened': {
        'Screened': is_screened,
        'Not Screened': is_not_screened,
    },
    'Deflections': {
        'Deflected': is_deflected,
        'Not Deflected': is_not_deflected,
    },
    '1-Timer': {
        '1-Timer Taken': is_one_timer,
        '1-Timer Not Taken': is_not_one_timer,
    },
    'Shot Location': {
        'Inner Slot': is_inner_slot,
        'Outer Slot': is_outer_slot,
        'Slot': is_slot,
        'Outside': is_outside,
    },
    'Pressure': {
        'Pressure': is_pressured,
        'No Pressure': is_not_pressured,
    },
}

SHOTS = FilterGroups('shot', SHOT_FILTERS)


# --- Base sets ------------------------------------------------------------

def all_shots(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'shot']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def shots_matching(shots: Iterable[Event], group: str, item: str) -> list[Event]:
    """Shots passing one named filter item."""
    return SHOTS.matching(shots, group, item)


def filter_shots(shots: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_shots(shots, Result=['On Net'], Shot_Location=['Inner Slot'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return SHOTS.filter(shots, **selections)


def group_breakdown(shots: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given shots."""
    return SHOTS.breakdown(shots)


def check_groups_exhaustive(shots: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every shot.

    The property the filter UI depends on: tick everything in a group and you
    get all the shots back.
    """
    return SHOTS.check_exhaustive(shots)


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game, raw_game: RawGame | None = None) -> dict:
    """raw_game is accepted for backwards compatibility and no longer used --
    play_section now comes off the Event directly."""
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        shots = all_shots(game, team_id)
        res[team_id] = {'All Shot Attempts': shots, **SHOTS.rows(shots)}
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nSHOT STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))




def season_stats(league: int, season: str):
    from hockey.catalog import DataCatalog
    catalog = DataCatalog(_settings().data_root_dir)
    game_ids = catalog.scheduled_game_ids(17, "20252026")


    res = []
    for game_id in game_ids[:50]:
        print(game_id)
        raw_game = RawGame(game_id, _settings().data_root_dir)
        game = build_game(raw_game)
        # r = cf.with_types(game.events, ["d2d","offboards"])
        # r2 = cf.with_flags(game.events, "lowhigh")
        shots = all_shots(game)
        #for event in game.events:
        #    # res += event.flags
        #    res.append(event.type)
        #res = list(set(res))
        print(len(res))
    game_ids = catalog.scheduled_game_ids(1, "20252026")

if __name__ == "__main__":
    #season_stats(17,"20252026")
    #exit(0)
    GAME_ID = 191848
    GAME_ID = 186461
    # raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
    #               playsequence_source="playsequence_compiled")
    # game = build_game(raw)
    conn = open_database_azure("hockey_v2_test")
    game = build_game_from_db(GAME_ID, conn)
    # res = get_full_data(game)
    # print_res(res)

    shots = all_shots(game)
    p = shots_matching(shots,"Shot Location", "Inner Slot")
    print("\nexhaustiveness:", check_groups_exhaustive(shots))
    print("inner-slot 1-timers on net:",
          len(filter_shots(shots, Shot_Location=['Inner Slot'],
                           **{'1-Timer': ['1-Timer Taken']}, Result=['On Net'])))
