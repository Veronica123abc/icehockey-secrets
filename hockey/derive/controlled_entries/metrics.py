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

def oz_carry(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    events = [e for e in events if
             e['name'] in ['controlledentry'] and 'carry' in e['type']]
    return events

def oz_pass(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    events = [e for e in events if
              e['name'] in ['controlledentry'] and 'pass' in e['type']]
    return events

def _whith_play_after(events: Iterable):
    return [e for e in events if 'withplay' in e['type']]

def _successul(events: Iterable):
    return [e for e in events if e['outcome'] == 'successful']

def _failed(events: Iterable):
    return [e for e in events if e['outcome'] == 'failed']

def _for_team(events: Iterable, team_id: int) -> Iterable:
    return [e for e in events if e['team_id'] == str(team_id)]

def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {
        team_ids[0]:{},
        team_ids[1]:{},
    }

    for team_id in team_ids:
        all_carries = oz_carry(game)
        all_team_carries = _for_team(all_carries, team_id)
        all_team_carries_with_play = _whith_play_after(all_team_carries)

        all_pass_attempts = oz_pass(game)
        all_team_pass_attempts = _for_team(all_pass_attempts, team_id)
        all_successful_team_pass = _successul(all_team_pass_attempts)
        all_failed_team_pass_attempts = _failed(all_team_pass_attempts)
        all_successful_pass_with_play = _whith_play_after(all_successful_team_pass)

        res[team_id] = {



            "Total Successful OZ Entries": all_team_carries + all_successful_team_pass,
            "Successful OZ Carries": all_team_carries,
            "Carries with play after": all_team_carries_with_play,

            "Attempted Entries with pass": all_team_pass_attempts,
            "Successful Entries with pass": all_successful_team_pass,
            "Entries with pass and play after": all_successful_pass_with_play,

            "Attempted Controlled Entries": all_team_carries + all_team_pass_attempts,
            "Successful Controlled Entries": all_team_carries + all_successful_team_pass
        }


    return res

def print_res(res):
    for k in list(res.keys()):
        print(k)
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))

if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 191504
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    team_id=308

    k = get_full_data(game)

    print_res(k)
    oz_carries = oz_carry(game)
    oz_carries = _for_team(oz_carries, team_id)
    print()
    print('oz carries: ', len(oz_carries))
    oz_carries = _successul(oz_carries)
    print('successful carrries: ', len(oz_carries))
    oz_carries = _whith_play_after(oz_carries)
    print('carries with play after: ', len(oz_carries))

    oz_passes = oz_pass(game)
    oz_passes = _for_team(oz_passes, team_id)
    print('oz passes: ', len(oz_passes))
    oz_passes = _successul(oz_passes)
    print('successful passes: ', len(oz_passes))
    oz_carries = _whith_play_after(oz_passes)
    print('passes with play after: ', len(oz_carries))
    exit(0)

