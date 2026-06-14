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



def dumpin(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    events = [e for e in events if
             e['name'] in ['dumpin']]
    return events

def chipin(game: Game) -> Iterable[Event]:
    events = dumpin(game)
    events = [e for e in events if 'chip' in e['type']]
    return events

def dumpin_recovery(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    events = [
        e for e in events if
        e['name'] in ['dumpinrecovery'] and
        'offensive' in e['type']
    ]
    return events

def dumpin_entry(game: Game) -> Iterable[Event]:
    # A successful dumpinentry <=> dumprecovery
    events = [e.raw for e in game.events]
    events = [
        e for e in events if
        e['name'] == 'dumpinentry'
    ]
    return events

def _selfchipin(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'selfchipin' in e['type']]

def _with_shot(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e['type']]

def _with_shotonnet(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e['type']]

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
    team_id=322

    events = dumpin(game)
    events = _for_team(events, team_id)
    events = _for_team(events, team_id)
    print('dumpins', len(events))
    events = _successul(events)
    print('succesful dumpins: ', len(events))

    events = chipin(game)
    events = _for_team(events, team_id)
    print('chipins: ', len(events))
    events = _successul(events)
    print('successful chipins: ', len(events))

    events = dumpin_recovery(game)
    events = _for_team(events, team_id)
    print('dumpin recoveries: ', len(events))
    recoveries = events
    events = _selfchipin(events)
    print('selfchipins: ', len(events))
    events = _with_shot(events)
    print('self chip-ins with shot', len(events))
    events = _with_shotonnet(recoveries)
    print('recoveries with shot on net', len(events))
    events = _whith_play_after(recoveries)
    print('recoveries with play after', len(events))


    # events = dumpin_entry(game)
    # events = _for_team(events, team_id)
    # events = _successul(events)
    # #events = _with_shotonnet(events)
    # print('dumpin entries: ', len(events))

