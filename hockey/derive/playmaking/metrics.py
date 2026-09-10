#!/usr/bin/python
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.data_collection.sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.normalize.update_game import update_game
from hockey.model.game import Game
from hockey.derive.base_events import index_by_event_id, base_event

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)




def expected_goals_all_shots(game: Game, team_id:int | str| None=None) -> Iterable[Event]:
    # Event.grade is the expected_goals_all_shots_grade, kept under its old name.
    events = [e for e in game.events if e.grade is not None]
    if team_id:
        events = _for_team(events, team_id)
    return events

def expected_goals_on_net(game: Game) -> Iterable[Event]:
    return [e for e in game.events if e.expected_goals_on_net_grade is not None]

def _xG_category(events: Iterable[Event], category: str) -> Iterable[Event]:
    """Chances of one expected-goals grade ('A', 'B', 'C')."""
    return [e for e in events if e.grade == category]

def scoring_chances(game: Game, team_id:int | str| None=None) -> Iterable[Event]:
    """Scoring chances, with their expected-goals grade already on the Event.

    RawGame used to be needed here to fetch the base shot's grade out of
    playsequence.json. It is not any more: build_game links the two
    playsequence files, so ``Event.grade`` and
    ``Event.expected_goals_all_shots`` are populated on the chance itself.
    """
    events = [e for e in game.events if e.name == "scoringchance"]
    if team_id:
        events = _for_team(events, team_id)
    return events

# --- Scoring chance outcome subclasses ------------------------------------
#
# Every scoring chance hangs off a base 'shot' event (40/40, 54/54, 40/40 in
# the sample games), and the chance mirrors that shot: its own outcome equals
# the shot's, and 'blocked' appears in its own ``type`` exactly when the base
# shot is 'slotblocked' (agreement 100% across three games). So blocked /
# on net / missed are read off the chance itself -- no base lookup needed.
#
# blocked | missed | on net is a true partition: the three sum to the chance
# total in every game checked, and every blocked chance has outcome 'failed'.
# Goals are a SUBSET of on net, not a fourth bucket.


def scoring_chances_blocked(chances: Iterable[Event]) -> list[Event]:
    """Chances whose shot was blocked ('blocked' in the chance type)."""
    return [e for e in chances if 'blocked' in e.type]


def scoring_chances_on_net(chances: Iterable[Event]) -> list[Event]:
    """Chances whose shot reached the net. Includes goals."""
    return [e for e in chances if e.outcome == 'successful']


def scoring_chances_missed(chances: Iterable[Event]) -> list[Event]:
    """Chances that missed the net -- failed, but not blocked."""
    return [e for e in chances if 'blocked' not in e.type and e.outcome == 'failed']


def scoring_chances_goals(game: Game, chances: Iterable[Event]) -> list[Event]:
    """Chances that were scored.

    Needs ``game`` because the goal marker is the 'withgoal' flag on the base
    shot event -- the scoring chance itself carries no flags at all. Always a
    subset of :func:`scoring_chances_on_net`; fewer than the game's total
    goals, since not every goal comes from a scoring chance.
    """
    index = index_by_event_id(game.events)
    out = []
    for e in chances:
        base = base_event(e, index)
        if base is not None and 'withgoal' in base.flags:
            out.append(e)
    return out


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

# The slot as SportLogIQ sections it. The three OZ sections below are exactly
# the shots typed 'slot'/'slotblocked' (54 == 49+5 in game 186461), which is
# what makes them the right definition of "in the slot"; the *DZ twins are the
# defensive-zone mirror and are deliberately excluded from offensive plays.
OZ_SLOT_SECTIONS = frozenset({'innerSlot', 'eastOuterSlot', 'westOuterSlot'})


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

def _with_shot(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e.type]

def _with_slotshot(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if 'withslotshot' in e.flags]

def _with_shotonnet(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if 'withshotonnet' in e.flags]

def _with_play_after(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if 'withplayafter' in e.flags]

def _successul(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if e.outcome == 'successful']

def _failed(events: Iterable[Event]) -> Iterable[Event]:
    return [e for e in events if e.outcome == 'failed']

def _for_team(events: Iterable[Event], team_id: int | str) -> Iterable[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def get_full_data(game: Game) -> dict:
    columns_to_add = [
        'expected_goals_all_shots_grade',
        'expected_goals_all_shots',
    ]
    # game = update_game(game, raw, columns_to_add)
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {
        team_ids[0]:{},
        team_ids[1]:{},
    }

    for team_id in team_ids:
        all_expected_goals = scoring_chances(game, team_id=team_id)

        all_expected_goals_A = _xG_category(all_expected_goals, 'A')
        all_expected_goals_B = _xG_category(all_expected_goals, 'B')
        all_expected_goals_C = _xG_category(all_expected_goals, 'C')

        chances_goal = scoring_chances_goals(game, all_expected_goals)
        chances_on_net = scoring_chances_on_net(all_expected_goals)
        chances_missed = scoring_chances_missed(all_expected_goals)
        chances_blocked = scoring_chances_blocked(all_expected_goals)


        categories = ogp_categories(game, team_id=team_id)

        res[team_id] = {

            'All scoring chances': all_expected_goals,
            'A chances': all_expected_goals_A,
            'B chances': all_expected_goals_B,
            'C chances': all_expected_goals_C,
            'Chances - goals': chances_goal,
            'Chances - on net (incl. goals)': chances_on_net,
            'Chances - missed': chances_missed,
            'Chances - blocked': chances_blocked,
            **{f'OGP - {label}': events for label, events in categories.items()},
            'OGP - goals not otherwise counted': ogp_goals_not_otherwise_counted(game, team_id=team_id),
            'OGP total (deduped)': ogp(game, team_id=team_id),
        }
    return res

def print_res(res):
    for k in list(res.keys()):
        print(f"\nOffensive Generating Plays FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))

if __name__ == "__main__":
    GAME_ID = 191848
    #GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    raw2 = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence")
    game = build_game(raw)
    game2 = build_game(raw2)
    team_id=322
    # a=ogp(game)

    res = get_full_data(game)
    print_res(res)
    #print(res)