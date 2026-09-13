#!/usr/bin/python
"""Playmaking metrics.

Two distinct shapes live here, deliberately:

* SCORING CHANCES are one population filtered by :data:`SCORING_CHANCE_FILTERS`
  -- grade, result and how the chance was generated.
* OFFENCE GENERATING PLAYS are a CATEGORY LIST, not a filter group: the eight
  categories in CLAUDE.md are drawn from different event names (passes,
  carries, lprs, shots), so no single population can be filtered into them.
  They stay as :func:`ogp_categories`, deduped by :func:`ogp`.

Every scoring chance hangs off a base 'shot' event (94/94 over two games), and
the chance mirrors that shot: its own outcome equals the shot's, and 'blocked'
appears in its own ``type`` exactly when the base shot is 'slotblocked'. So
blocked / on net / missed are read off the chance itself -- no base lookup
needed, and the three are a true partition (52+28+14 = 94). Goals are a SUBSET
of on net; the goal marker is the 'withgoal' flag on the BASE shot, so
:func:`scoring_chances_goals` needs the game and cannot be a predicate.

Group exhaustiveness, verified over games 186461 + 191848 (94 chances): Grade
29+23+31+11 and Result 52+28+14 each total 94. Chance Type overlaps by
construction -- 'otfcotc' is both off the forecheck and off the cycle, the
same deliberate overlap shooting's 'Slot' has -- so it carries an explicit
'Unclassified' item for the 18 chances typed 'none' or bare 'blocked'.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.base_events import index_by_event_id, base_event

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

# The slot as SportLogIQ sections it. The three OZ sections below are exactly
# the shots typed 'slot'/'slotblocked' (54 == 49+5 in game 186461), which is
# what makes them the right definition of "in the slot"; the *DZ twins are the
# defensive-zone mirror and are deliberately excluded from offensive plays.
OZ_SLOT_SECTIONS = frozenset({'innerSlot', 'eastOuterSlot', 'westOuterSlot'})


# --- Predicates -----------------------------------------------------------
# One per filter item. Kept as Event -> bool so groups can be combined and
# their exhaustiveness checked mechanically (see check_groups_exhaustive).

def is_grade_a(event: Event) -> bool:
    return event.grade == 'A'


def is_grade_b(event: Event) -> bool:
    return event.grade == 'B'


def is_grade_c(event: Event) -> bool:
    return event.grade == 'C'


def is_ungraded(event: Event) -> bool:
    """No expected-goals grade. Keeps the Grade group exhaustive -- 11 of 94
    chances in the sample games carry none."""
    return event.grade not in ('A', 'B', 'C')


def is_blocked(event: Event) -> bool:
    return 'blocked' in (event.type or '')


def is_on_net(event: Event) -> bool:
    """Reached the net. Includes goals, as shots-on-net conventionally does."""
    return event.outcome == 'successful'


def is_missed(event: Event) -> bool:
    """Missed the net: failed, but not blocked."""
    return not is_blocked(event) and event.outcome == 'failed'


def is_off_the_rush(event: Event) -> bool:
    return 'otr' in (event.type or '')


def is_off_the_cycle(event: Event) -> bool:
    return 'otc' in (event.type or '')


def is_off_the_forecheck(event: Event) -> bool:
    return 'otfc' in (event.type or '')


def is_unclassified_chance(event: Event) -> bool:
    """None of the three generation types -- type 'none' or bare 'blocked'."""
    kind = event.type or ''
    return not ('otr' in kind or 'otc' in kind or 'otfc' in kind)


def is_second_chance(event: Event) -> bool:
    return '2ndchance' in (event.type or '')


def is_not_second_chance(event: Event) -> bool:
    return not is_second_chance(event)


# --- Filter groups --------------------------------------------------------

Predicate = Callable[[Event], bool]

SCORING_CHANCE_FILTERS: dict[str, dict[str, Predicate]] = {
    'Grade': {
        'A': is_grade_a,
        'B': is_grade_b,
        'C': is_grade_c,
        'Ungraded': is_ungraded,
    },
    'Result': {
        'On Net': is_on_net,
        'Missed': is_missed,
        'Blocked': is_blocked,
    },
    'Chance Type': {
        'Off the Rush': is_off_the_rush,
        'Off the Cycle': is_off_the_cycle,
        'Off the Forecheck': is_off_the_forecheck,
        'Unclassified': is_unclassified_chance,
    },
    '2nd Chance': {
        '2nd Chance': is_second_chance,
        'Not 2nd Chance': is_not_second_chance,
    },
}


# --- Base sets ------------------------------------------------------------

def scoring_chances(game: Game, team_id: int | str | None = None) -> list[Event]:
    """Scoring chances, with their expected-goals grade already on the Event.

    RawGame used to be needed here to fetch the base shot's grade out of
    playsequence.json. It is not any more: build_game links the two
    playsequence files, so ``Event.grade`` and
    ``Event.expected_goals_all_shots`` are populated on the chance itself.
    """
    events = [e for e in game.events if e.name == "scoringchance"]
    return _for_team(events, team_id) if team_id else events


def expected_goals_all_shots(game: Game, team_id: int | str | None = None) -> list[Event]:
    # Event.grade is the expected_goals_all_shots_grade, kept under its old name.
    events = [e for e in game.events if e.grade is not None]
    return _for_team(events, team_id) if team_id else events


def expected_goals_on_net(game: Game) -> list[Event]:
    return [e for e in game.events if e.expected_goals_on_net_grade is not None]


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


def chances_matching(chances: Iterable[Event], group: str, item: str) -> list[Event]:
    """Scoring chances passing one named filter item."""
    return _matching(chances, SCORING_CHANCE_FILTERS, group, item)


def filter_chances(chances: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_chances(chances, Grade=['A'], Chance_Type=['Off the Rush'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return _apply(chances, SCORING_CHANCE_FILTERS, **selections)


def group_breakdown(chances: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given chances."""
    chances = list(chances)
    return {group: {item: [e for e in chances if predicate(e)]
                    for item, predicate in items.items()}
            for group, items in SCORING_CHANCE_FILTERS.items()}


def check_groups_exhaustive(chances: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every chance."""
    chances = list(chances)
    out = {}
    for group, items in SCORING_CHANCE_FILTERS.items():
        covered = {id(e) for e in chances if any(p(e) for p in items.values())}
        out[group] = len(covered) == len(chances)
    return out


# --- Named sets kept for existing callers ---------------------------------

def _xG_category(events: Iterable[Event], category: str) -> list[Event]:
    """Chances of one expected-goals grade ('A', 'B', 'C')."""
    return [e for e in events if e.grade == category]


def scoring_chances_blocked(chances: Iterable[Event]) -> list[Event]:
    return [e for e in chances if is_blocked(e)]


def scoring_chances_on_net(chances: Iterable[Event]) -> list[Event]:
    return [e for e in chances if is_on_net(e)]


def scoring_chances_missed(chances: Iterable[Event]) -> list[Event]:
    return [e for e in chances if is_missed(e)]


def scoring_chances_goals(game: Game, chances: Iterable[Event]) -> list[Event]:
    """Chances that were scored.

    Needs ``game`` because the goal marker is the 'withgoal' flag on the base
    shot event -- the scoring chance itself carries no flags at all, which is
    why this is a function rather than an item in the Result group. Always a
    subset of :func:`scoring_chances_on_net`.
    """
    index = index_by_event_id(game.events)
    out = []
    for e in chances:
        base = base_event(e, index)
        if base is not None and 'withgoal' in base.flags:
            out.append(e)
    return out


# --- Offence generating plays --------------------------------------------
# A category list, not a filter group: each category is drawn from a different
# event name, so there is no single population to filter.

def _successful_passes(game: Game, team_id=None) -> list[Event]:
    events = game.events
    if team_id:
        events = _for_team(events, team_id)
    return [e for e in events if e.name == "pass" and e.outcome == "successful"]


def ogp_passes_otr(game, team_id=None) -> list[Event]:
    return [e for e in _successful_passes(game, team_id) if e.type == "rush"]


def ogp_passes_1timer(game, team_id=None) -> list[Event]:
    return [e for e in _successful_passes(game, team_id) if "1timer" in e.flags]


def ogp_passes_to_slot(game, team_id=None) -> list[Event]:
    return [e for e in _successful_passes(game, team_id) if e.type == "slot"]


def ogp_carries_to_slot(game, team_id=None) -> list[Event]:
    """Carries into the slot -- a dedicated event name, not a carry subtype.

    Plain 'carry' events are logged at their START (boards, points, NZ) and
    never carry a slot play_section, so they cannot answer this. The supplier
    emits 'carrytoslot' instead: always OZ, always successful.
    """
    events = _for_team(game.events, team_id) if team_id else game.events
    return [e for e in events if e.name == 'carrytoslot']


def ogp_lpr_in_slot(game, team_id=None) -> list[Event]:
    """Loose puck recoveries in the offensive-zone slot.

    LPR types carry no slot value, so this goes on play_section. DZ slot
    sections are excluded -- recovering a puck in your own slot is not an
    offence-generating play.
    """
    events = _for_team(game.events, team_id) if team_id else game.events
    return [e for e in events
            if e.name == 'lpr' and e.play_section in OZ_SLOT_SECTIONS]


def ogp_shots_on_net_from_slot(game, team_id=None) -> list[Event]:
    """Slot shots that reached the net (supplier shorthand SLOT SHOT FOR ONNET).

    Type 'slot' excludes 'slotblocked' by construction, and a successful
    outcome is 'on net' as used throughout ``shooting/``.
    """
    events = _for_team(game.events, team_id) if team_id else game.events
    return [e for e in events
            if e.name == 'shot' and e.type == 'slot' and e.outcome == 'successful']


def ogp_outside_shots_with_rebound(game, team_id=None) -> list[Event]:
    """Outside shots that generated a rebound.

    Covers 'outside' and 'outsideblocked' alike -- a blocked shot can still
    produce a rebound, and the supplier flags it the same way.
    """
    events = _for_team(game.events, team_id) if team_id else game.events
    return [e for e in events
            if e.name == 'shot' and 'outside' in e.type and 'withrebound' in e.flags]


def ogp_goals(game, team_id=None) -> list[Event]:
    """The shots that scored.

    Uses the 'withgoal' shot rather than the separate 'goal' event: the goal
    event shares no possession key with its shot (0/9 overlap), while
    withgoal-flagged shots match the goal count exactly (9/9, 2/2). Taking the
    shot also lets :func:`ogp` dedupe goals against the other categories,
    which is what "any goal not also one of the above" asks for.
    """
    events = _for_team(game.events, team_id) if team_id else game.events
    return [e for e in events if e.name == 'shot' and 'withgoal' in e.flags]


def ogp_categories(game, team_id=None) -> dict[str, list[Event]]:
    """The eight offence-generating play categories from CLAUDE.md, in order."""
    return {
        'Passes to the slot': ogp_passes_to_slot(game, team_id),
        'Passes off the rush': ogp_passes_otr(game, team_id),
        'Passes for 1-timers': ogp_passes_1timer(game, team_id),
        'Carries to the slot': ogp_carries_to_slot(game, team_id),
        'LPR in the slot': ogp_lpr_in_slot(game, team_id),
        'Shots on net from the slot': ogp_shots_on_net_from_slot(game, team_id),
        'Outside shots generating a rebound': ogp_outside_shots_with_rebound(game, team_id),
        'Goals': ogp_goals(game, team_id),
    }


def ogp_goals_not_otherwise_counted(game, team_id=None) -> list[Event]:
    """Goals the other seven categories do not already contain.

    This is the CLAUDE.md list's last line made explicit; :func:`ogp` gets the
    same effect from deduping, so this exists for reporting.
    """
    cats = ogp_categories(game, team_id)
    goals = cats.pop('Goals')
    others = {e.get_raw('event_id') for evs in cats.values() for e in evs}
    return [e for e in goals if e.get_raw('event_id') not in others]


def ogp(game, team_id=None) -> list[Event]:
    """Every offence-generating play, deduped.

    Goals are added last and collapse into whichever category already holds
    them, so a slot shot that scored counts once -- "any goal not also one of
    the above".
    """
    all_plays = [e for evs in ogp_categories(game, team_id).values() for e in evs]
    # deduped on the raw event_id, which is a string on every source
    return list({e.get_raw('event_id'): e for e in all_plays}.values())


# --- Helpers --------------------------------------------------------------

def _for_team(events: Iterable[Event], team_id: int | str) -> list[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    for team_id in team_ids:
        chances = scoring_chances(game, team_id=team_id)

        out = {'All Scoring Chances': chances}
        for group, items in group_breakdown(chances).items():
            for item, events in items.items():
                out[f'{group} - {item}'] = events
        # Not a Result item: needs the base shot's 'withgoal' flag.
        out['Result - Goals'] = scoring_chances_goals(game, chances)

        categories = ogp_categories(game, team_id=team_id)
        out.update({f'OGP - {label}': events for label, events in categories.items()})
        out['OGP - goals not otherwise counted'] = ogp_goals_not_otherwise_counted(
            game, team_id=team_id)
        out['OGP total (deduped)'] = ogp(game, team_id=team_id)

        res[team_id] = out
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nPLAYMAKING STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)

    chances = scoring_chances(game)
    print("\nexhaustiveness:", check_groups_exhaustive(chances))
    print("A chances off the rush:",
          len(filter_chances(chances, Grade=['A'], Chance_Type=['Off the Rush'])))
