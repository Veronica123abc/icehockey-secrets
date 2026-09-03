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
    # NOT Event.grade: add_raw_base_events writes the base event's grade into
    # the raw payload under 'grade', and that injected value is what we want.
    return [e for e in events if e.get_raw('grade') == category]

def get_base_event(all_events: Iterable[Event], event: Event) -> Event | None:
    # event_id stays on the raw payload: derived events carry a composite id
    # ("5453663996-314651935") that Event.event_id parses to None.
    base_event_id = event.get_raw('event_id').split('-')[1]
    base_event = [e for e in all_events if e.get_raw('event_id') == base_event_id]
    if len(base_event) != 1:
        return None
    return(base_event[0])

def scoring_chances(game: Game, raw:RawGame, team_id:int | str| None=None) -> Iterable[Event]:
    all_events = game.events
    events = [e for e in all_events if e.name == "scoringchance"]
    events = add_raw_base_events(all_events, events, raw)
    if team_id:
        events = _for_team(events, team_id)
    return events

def add_raw_base_events(all_events: Iterable[Event], events: Iterable[Event], raw_game:RawGame) -> Iterable[Event]:
    """Fold the base event's xG grade into each chance's raw payload.

    Event is frozen, so the injected 'grade'/'xg_value' land in ``e.raw`` and
    are read back with get_raw -- see _xG_category.
    """
    res = []
    for e in events:
        event_id = e.get_raw('event_id')
        if event_id is not None and '-' in str(event_id):
            base_event_id = str(event_id).split('-')[1]
            base_events = [b for b in all_events if b.get_raw('event_id') == base_event_id]
            if len(base_events) != 1:
                print("Missing base event")
                continue
            base_event = base_events[0]
            e.raw['grade'] = raw_game.full_event_field(
                base_event.current_possession, base_event.current_play_in_possession,
                'shot', 'expected_goals_all_shots_grade')
            e.raw['xg_value'] = raw_game.full_event_field(
                base_event.current_possession, base_event.current_play_in_possession,
                'shot', 'expected_goals_all_shots')
        res.append(e)
    return res

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

def ogp(game, team_id=None) -> list[Event]:
    all_ogp_passes = (ogp_passes_otr(game, team_id)
                      + ogp_passes_1timer(game, team_id)
                      + ogp_passes_to_slot(game, team_id))
    # deduped on the raw event_id, which is a string on every source
    return list({e.get_raw('event_id'): e for e in all_ogp_passes}.values())

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


def get_full_data(game: Game, raw_game:RawGame) -> dict:
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
        all_expected_goals = scoring_chances(game, raw_game, team_id=team_id)
        #add_raw_base_events(all_expected_goals, raw_game)

        all_expected_goals_A = _xG_category(all_expected_goals, 'A')
        all_expected_goals_B = _xG_category(all_expected_goals, 'B')
        all_expected_goals_C = _xG_category(all_expected_goals, 'C')


        ogp_otr = ogp_passes_otr(game, team_id=team_id)
        ogp_1timer =  ogp_passes_1timer(game, team_id=team_id)
        ogp_to_slot = ogp_passes_to_slot(game, team_id=team_id)
        all_ogp_passes = ogp_otr + ogp_1timer + ogp_to_slot
        ogp_all_passes = list({item.get_raw('event_id'): item for item in all_ogp_passes}.values())

        res[team_id] = {

            'All scoring chances': all_expected_goals,
            'A chances': all_expected_goals_A,
            'B chances': all_expected_goals_B,
            'C chances': all_expected_goals_C,
            'OGP Passes Off the Rush': ogp_otr,
            'OGP 1timer Passes': ogp_1timer,
            'OGP Passes to slot': ogp_to_slot,
            'OGP Passes':  ogp_all_passes,
        }
    return res

def print_res(res):
    for k in list(res.keys()):
        print(f"\nOffensive Generating Plays FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))

if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    raw2 = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence")
    game = build_game(raw)
    game2 = build_game(raw2)
    team_id=322
    # a=ogp(game)

    res = get_full_data(game, raw)
    print_res(res)
    print(res)