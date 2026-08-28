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

def opposition_dumpin_recoveries(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    exits = [e for e in events if
             e['name'] in ['dumpinrecovery'] and
             e['type'] == 'defensive'
            ]
    return exits

def controlled_exits(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    exits = [e for e in events if
             e['name'] in ['controlledexit']
             and e['outcome'] == 'successful']
    return exits

def dz_carry_outs(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    exits = [e for e in events if
             e['name'] in ['controlledexit'] and
             'carry' in e['type']]
    return exits

def exit_pass(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    exits = [e for e in events if
             e['name'] in ['controlledexit'] and
             'pass' in e['type']]
    return exits

def dumpouts(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    exits = [e for e in events if
             e['name'] in ['dumpout']]
    return exits

def _with_play_after(events: Iterable):
    return [e for e in events if 'withplay' in e['type']]

def _successful(events: Iterable):
    return [e for e in events if e['outcome'] == 'successful']

def _failed(events: Iterable):
    return [e for e in events if e['outcome'] == 'failed']

def _for_team(events: Iterable, team_id: int) -> Iterable:
    return [e for e in events if e['team_id'] == str(team_id)]

def get_full_data(game):
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {
        team_ids[0]:{},
        team_ids[1]:{},
    }

    for team_id in team_ids:
        all_dumpouts = dumpouts(game)
        all_dumpouts = _for_team(all_dumpouts, team_id)
        successful_dumpouts = _successful(all_dumpouts)
        carry_outs = dz_carry_outs(game)
        carry_outs = _for_team(carry_outs, team_id)
        carry_outs_with_play = _with_play_after(carry_outs)
        exit_passes = exit_pass(game)
        exit_passes = _for_team(exit_passes, team_id)
        successful_exit_passes = _successful(exit_passes)
        successful_exit_passes_with_play = _with_play_after(successful_exit_passes)
        opp_dumpin_recoveries = opposition_dumpin_recoveries(game)
        opp_dumpin_recoveries = _for_team(opp_dumpin_recoveries, team_id)
        successful_dumpin_recoveries = _successful(opp_dumpin_recoveries)

        res[team_id] = {
            'Dumpouts': all_dumpouts,
            'Successful Dumpouts': successful_dumpouts,
            'carry_outs': carry_outs,
            'carry_outs_with_play': carry_outs_with_play,
            'exit_passes': exit_passes,
            'Successful Exit Passes': successful_exit_passes,
            'Successful Exit Passes With Play': successful_exit_passes_with_play,
            'Opposition Dumpin Recoveries': opp_dumpin_recoveries,
            'Successful Opposition Dumpin Recoveries': successful_dumpin_recoveries,

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

    res = get_full_data(game)
    print_res(res)
