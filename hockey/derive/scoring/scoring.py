#!/usr/bin/python
"""Scoring metrics.

Two populations live here, each with its own filter dictionary:

* ``goal`` -- one per goal scored, credited to the scorer. The separate
  ``goalagainst`` event is the goalie's, not the scorer's, so it is not a
  population here.
* ``assist`` -- one per assist credited, and a goal may carry two. ``type``
  says which: 'first' or 'second'.

GOALS HAVE NO FILTER GROUPS, and the empty dictionary is deliberate rather
than unfinished. This folder's CLAUDE.md defines four metrics -- Goals,
Assist, 1st Assist, 2nd Assist -- and three of them are the assist population
and its two items. "Goals" is the whole goal population, which is the ``All``
lane. Verified across the 410-game database: ``type`` is 'none' on all 2210
goals, ``outcome`` 'successful' on all of them, and ``zone`` 'oz' on all of
them, so there is nothing on the event to partition by. The only sub-sets the
data would support are the ``gwg`` (380) and ``penaltyshot`` (10) flags, and
neither is a metric the spec asks for.

Group exhaustiveness, verified over the whole database (3675 assists): Assist
Type 2036+1639 totals 3675 exactly, with no assist untyped -- so that group
needs no 'Untagged' complement, unlike dump-in Technique. Game 186461 alone
has 9 goals, 9 first assists and 6 second assists.

AN ASSIST'S BASE EVENT IS NOT ITS GOAL. ``sl_base_event_id`` on all 3675
assists resolves to another assist, never to the goal, so there is no
base-event helper here of the kind ``possession`` has -- linking an assist to
the goal it fed would need something other than that column.

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

def is_first_assist(event: Event) -> bool:
    """The primary assist. Exact match, not a substring test -- an assist's
    type is exactly 'first' or 'second', never a concatenation."""
    return event.type == 'first'


def is_second_assist(event: Event) -> bool:
    return event.type == 'second'


# --- Filter groups --------------------------------------------------------

#: Empty on purpose -- see the module docstring. Kept as a named dictionary so
#: a group can be added here without changing anything that consumes it.
GOAL_FILTERS: dict[str, dict[str, Predicate]] = {}

ASSIST_FILTERS: dict[str, dict[str, Predicate]] = {
    'Assist Type': {
        '1st Assist': is_first_assist,
        '2nd Assist': is_second_assist,
    },
}

GOALS = FilterGroups('goal', GOAL_FILTERS)
ASSISTS = FilterGroups('assist', ASSIST_FILTERS)


# --- Base sets ------------------------------------------------------------

def all_goals(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every goal, credited to the scoring team."""
    events = [e for e in game.events if e.name == 'goal']
    return for_team(events, team_id) if team_id else events


def all_assists(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Every assist credited, first and second together."""
    events = [e for e in game.events if e.name == 'assist']
    return for_team(events, team_id) if team_id else events


def first_assists(game: Game, team_id: int | str | None = None) -> list[Event]:
    return [e for e in all_assists(game, team_id) if is_first_assist(e)]


def second_assists(game: Game, team_id: int | str | None = None) -> list[Event]:
    return [e for e in all_assists(game, team_id) if is_second_assist(e)]


# --- Filtering ------------------------------------------------------------

def goals_matching(goals: Iterable[Event], group: str, item: str) -> list[Event]:
    """Goals passing one named filter item. The goal population defines no
    groups, so this raises until one is added."""
    return GOALS.matching(goals, group, item)


def filter_goals(goals: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection to goals. With no groups defined, any
    selection is unknown and an empty one returns every goal."""
    return GOALS.filter(goals, **selections)


def assists_matching(assists: Iterable[Event], group: str, item: str) -> list[Event]:
    """Assists passing one named filter item."""
    return ASSISTS.matching(assists, group, item)


def filter_assists(assists: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_assists(assists, Assist_Type=['1st Assist'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return ASSISTS.filter(assists, **selections)


def group_breakdown(assists: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given assists."""
    return ASSISTS.breakdown(assists)


def check_groups_exhaustive(assists: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every assist."""
    return ASSISTS.check_exhaustive(assists)


# --- Helpers --------------------------------------------------------------

_for_team = for_team


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        goals = all_goals(game, team_id)
        assists = all_assists(game, team_id)
        res[team_id] = {
            'All Goals': goals,
            **GOALS.rows(goals),
            'All Assists': assists,
            # No prefix: the goal population contributes no group names, so
            # nothing here can collide with one.
            **ASSISTS.rows(assists),
        }
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nSCORING STATS FOR {k}")
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

    goals = all_goals(game)
    assists = all_assists(game)
    print(f"\n{len(goals)} goals, {len(assists)} assists "
          f"({len(first_assists(game))} first, {len(second_assists(game))} second)")
    print("exhaustiveness:", check_groups_exhaustive(assists))
    print("1st assists via filter:",
          len(filter_assists(assists, Assist_Type=['1st Assist'])))
