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

def _whith_play_after(events: Iterable):
    return [e for e in events if 'withplay' in e['type']]

def _successul(events: Iterable):
    return [e for e in events if e['outcome'] == 'successful']

def _failed(events: Iterable):
    return [e for e in events if e['outcome'] == 'failed']

def _for_team(events: Iterable, team_id: int) -> Iterable:
    return [e for e in events if e['team_id'] == str(team_id)]


if __name__ == "__main__":
    GAME_ID = 204628
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    team_id=32

    exits = exit_pass(game)
    exits = _for_team(exits, team_id)
    print('exit passes: ', len(exits))
    exits = _successul(exits)
    print('successful exit passes: ', len(exits))
    exits = _whith_play_after(exits)
    print('successful exit passes with play after: ', len(exits))
    exits = dz_carry_outs(game)
    exits = _for_team(exits, team_id)
    print('carry outs: ', len(exits))
    exits = _whith_play_after(exits)
    print('carryouts with successful play after: ', len(exits))
    exits = dumpouts(game)
    exits = _for_team(exits, team_id)
    print('dumpouts: ', len(exits))
    exits = _successul(exits)
    print('successful dumpouts', len(exits))
    exits = opposition_dumpin_recoveries(game)
    exits = _for_team(exits, team_id)
    print('opposition dumpin recoveries: ', len(exits))
    exits = _successul(exits)
    print('successful opposition dumpin recoveries: ', len(exits))
