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




def expected_goals_all_shots(game: Game, team_id:int | str| None=None) -> Iterable[dict]:
    events = [e.raw for e in game.events]

    events = [
        e for e in events if
        e['expected_goals_all_shots_grade'] is not None
    ]
    if team_id:
        events = _for_team(events, team_id)
    return events

def expected_goals_on_net(game: Game) -> Iterable[dict]:
    events = [e.raw for e in game.events]
    events = [
        e for e in events if
        e['expected_goals_on_net_grade'] is not None
    ]
    return events

def _xG_category(events: Iterable, category: str) -> Iterable[dict]:
    return [e for e in events if e['grade'] == category]

def get_base_event(all_events, event):
    base_event_id = event['event_id'].split('-')[1]
    base_event = [e for e in all_events if e['event_id'] == base_event_id]
    if len(base_event) != 1:
        return None
    return(base_event[0])

def scoring_chances(game: Game, raw:RawGame, team_id:int | str| None=None) -> Iterable[dict]:
    all_events = [e.raw for e in game.events]
    events = [
        e for e in all_events if
        e['name'] == "scoringchance"
        # e['name'] == "shot"
    ]
    events = add_raw_base_events(all_events, events, raw)
    if team_id:
        events = _for_team(events, team_id)
    return events

def add_raw_base_events(all_events: Iterable[dict], events: Iterable[dict], raw_game:RawGame) -> Iterable[dict]:
    res = []
    for e in events:
        if '-' in e['event_id']:
            base_event_id = e['event_id'].split('-')[1]
            base_events = [e for e in all_events if e['event_id'] == base_event_id]
            if len(base_events) != 1:
                print("Missing base event")
                continue
            base_event = base_events[0]
            e['grade'] = raw_game.full_event_field(base_event['current_possession'],base_event['current_play_in_possession'], 'shot', 'expected_goals_all_shots_grade')
            e['xg_value'] = raw_game.full_event_field(base_event['current_possession'],
                                              base_event['current_play_in_possession'], 'shot',
                                              'expected_goals_all_shots')
            #e['grade'] = grade
        res.append(e)
    return res

def ogp_passes_otr(game, team_id=None):
    events = [e.raw for e in game.events]
    if team_id:
        events = [e for e in events if e["team_id"] == str(team_id)]
    passes = [e for e in events if e["name"] == "pass" and e["outcome"] == "successful"]
    ogp_passes_otr = [e for e in passes if e["type"] == "rush"]
    return ogp_passes_otr

def ogp_passes_1timer(game, team_id=None):
    events = [e.raw for e in game.events]
    if team_id:
        events = [e for e in events if e["team_id"] == str(team_id)]
    passes = [e for e in events if e["name"] == "pass" and e["outcome"] == "successful"]
    ogp_passes_1timer = [e for e in passes if "1timer" in e["flags"]]
    return ogp_passes_1timer

def ogp_passes_to_slot(game, team_id=None):
    events = [e.raw for e in game.events]
    if team_id:
        events = [e for e in events if e["team_id"] == str(team_id)]
    passes = [e for e in events if e["name"] == "pass" and e["outcome"] == "successful"]
    ogp_passes_to_slot = [e for e in passes if e["type"] == "slot"]
    return ogp_passes_to_slot

def ogp(game, team_id=None) -> list[dict]:
    events = [e.raw for e in game.events]
    if team_id:
        events = [e for e in events if e["team_id"] == str(team_id)]

    passes = [e for e in events if e["name"] == "pass" and e["outcome"] == "successful"]
    ogp_passes_otr = [e for e in passes if e["type"] == "rush"]
    ogp_passes_1timer = [e for e in passes if "1timer" in e["flags"]]
    ogp_passes_to_slot = [e for e in passes if e["type"] == "slot"]
    all_ogp_passes = ogp_passes_otr + ogp_passes_1timer + ogp_passes_to_slot
    ogp_all_passes = list({item["event_id"]: item for item in all_ogp_passes}.values())
    return ogp_all_passes


    return all_ogp_passes

def _with_shot(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e['type']]

def _with_slotshot(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withslotshot' in e['flags']]

def _with_shotonnet(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshotonnet' in e['flags']]

def _with_play_after(events: Iterable):
    return [e for e in events if 'withplayafter' in e['flags']]

def _successul(events: Iterable):
    return [e for e in events if e['outcome'] == 'successful']

def _failed(events: Iterable):
    return [e for e in events if e['outcome'] == 'failed']

def _for_team(events: Iterable, team_id: int | str) -> Iterable:
    return [e for e in events if e['team_id'] == str(team_id)]


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
        ogp_all_passes = list({item["event_id"]: item for item in all_ogp_passes}.values())

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