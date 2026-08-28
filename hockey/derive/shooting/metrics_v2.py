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
from hockey.model.game import Game
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)



def all_shots(game: Game) -> Iterable:
    events = [e.raw for e in game.events]
    events = [e for e in events if
             e['name'] in ['shot']]
    return events

def _deflected(events: Iterable) -> Iterable:
    return [e for e in events if 'deflected' in e['flags']]

def _with_pressure(events: Iterable) -> Iterable:
    return [e for e in events if 'withpressure' in e['flags']]

def _slot(events: Iterable) -> Iterable:
    return [e for e in events if 'slot' in e['type']]

def _inner_slot(events: Iterable, raw: RawGame) -> list:
    """Filter to inner-slot events. Lazily loads playsequence.json on first call via raw."""
    events = _slot(events)
    return [
        #e for e in events if raw.full_event_field(float(e['game_time']), e['name'], 'play_section') == 'innerSlot'
        e for e in events if raw.full_event_field(e['current_possession'], e['current_play_in_possession'], e['name'], 'play_section') == 'innerSlot'
        #if e.get('type') == 'slot' in e.get('ty')
        #and raw.full_event_field(float(e['game_time']), e['name'], 'play_section') == 'innerSlot'
    ]

def _outside(events: Iterable) -> Iterable:
    return [e for e in events if 'outside' in e['type']]

def _blocked(events: Iterable) -> Iterable:
    return [e for e in events if 'blocked' in e['type']]

def _missed(events: Iterable) -> Iterable:
    return [e for e in events if 'blocked' not in e['type'] and
            e['outcome'] == 'failed'
            ]




def _onnet(events: Iterable):
    return _successful(events)

def _successful(events: Iterable):
    return [e for e in events if e['outcome'] == 'successful']

def _failed(events: Iterable):
    return [e for e in events if e['outcome'] == 'failed']

def _for_team(events: Iterable, team_id: int) -> Iterable:
    return [e for e in events if e['team_id'] == str(team_id)]


def get_full_data(game, raw_game:RawGame):
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {
        team_ids[0]:{},
        team_ids[1]:{},
    }


    for team_id in team_ids:
        all_shot_attempts = all_shots(game)
        all_shot_attempts = _for_team(all_shot_attempts, team_id)
        onnet_shot_attempts = _onnet(all_shot_attempts)
        missed_shot_attempts = _missed(all_shot_attempts)
        blocked_shot_attempts = _blocked(all_shot_attempts)

        all_slot_shot_attempts = _slot(all_shot_attempts)
        onnet_slot_shot_attempts = _onnet(all_slot_shot_attempts)
        missed_slot_shot_attempts =  _missed(all_slot_shot_attempts)
        blocked_slot_shot_attempts = _blocked(all_slot_shot_attempts)

        all_inner_slot_shot_attempts = _inner_slot(all_shot_attempts, raw_game)
        all_inner_slot_shot_attempts = _for_team(all_inner_slot_shot_attempts, team_id)
        onnet_inner_slot_shots = _onnet(all_inner_slot_shot_attempts)
        missed_inner_slot_shots = _missed(all_inner_slot_shot_attempts)
        blocked_inner_slot_shots = _blocked(all_inner_slot_shot_attempts)

        res[team_id] = {
            'All Shot Attempts': all_shot_attempts,
            'Shots On Net': onnet_shot_attempts,
            'Missed Shots': missed_shot_attempts,
            'Blocked Shots': blocked_shot_attempts,
            'Slot Shot Attempts': all_slot_shot_attempts,
            'Slot Shots On Net': onnet_slot_shot_attempts,
            'Missed Slot Shots': missed_slot_shot_attempts,
            'Blocked Slot Shots': blocked_slot_shot_attempts,
            'Inner Slot Shot Attempts': all_inner_slot_shot_attempts,
            'Inner Slot Shots On Net': onnet_inner_slot_shots,
            'Missed Inner Slot Shots': missed_inner_slot_shots,
            'Blocked Inner Slot Shots': blocked_inner_slot_shots,
        }
    return res

def print_res(res):
    for k in list(res.keys()):

        print(f"\nSHOT STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    team_id=308

    res = get_full_data(game, raw) # Need to pass raw as well to recover play section from playsequence.json
    print_res(res)


    events = all_shots(game)
    events = _for_team(events, team_id)
    print(len(events))
    events = _slot(events)
    print(len(events))
    events = _onnet(events)
    print(len(events))
    events = _slot(events)
    print(len(events))
    events = _deflected(events)
    print(len(events))
    events = _successful(events)
    print(len(events))
    events = _outside(events)
    print(len(events))

    events = all_shots(game)
    events = _for_team(events, team_id)
    events = _inner_slot(events, raw)  # lazy: loads playsequence.json on first call
    events = _slot(events)
    print(len(events))


# def _with_shot(events: Iterable) -> Iterable[Event]:
#     return [e for e in events if 'withshot' in e['type']]
#
# def _with_shotonnet(events: Iterable) -> Iterable[Event]:
#     return [e for e in events if 'withshot' in e['type']]
#
# def _whith_play_after(events: Iterable):
#     return [e for e in events if 'withplay' in e['type']]