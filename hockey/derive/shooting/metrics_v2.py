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



def all_shots(game: Game) -> Iterable[Event]:
    events = [e.raw for e in game.events]
    events = [e for e in events if
             e['name'] in ['shot']]
    return events

def _deflected(event: Event):
    return [e for e in event if 'deflected' in e['flags']]
def _with_pressure(event: Event):
    return [e for e in event if 'withpressure' in e['flags']]

def _slot(event: Event):
    return [e for e in event if 'slot' in e['type']]

def _inner_slot(events: Iterable, raw: RawGame) -> list:
    """Filter to inner-slot events. Lazily loads playsequence.json on first call via raw."""
    return [
        e for e in events
        if e.get('type') == 'slot'
        and raw.full_event_field(float(e['game_time']), e['name'], 'play_section') == 'innerSlot'
    ]

def _outside(event: Event):
    return [e for e in event if 'outside' in e['type']]

def _blocked(event: Event):
    return [e for e in event if 'blocked' in e['type']]

def _missed(event: Event):
    return [e for e in event if 'blocked' not in e['type'] and
            e['outcome'] == 'failed'
            ]

def _with_shot(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e['type']]

def _with_shotonnet(events: Iterable) -> Iterable[Event]:
    return [e for e in events if 'withshot' in e['type']]

def _whith_play_after(events: Iterable):
    return [e for e in events if 'withplay' in e['type']]

def _onnet(events: Iterable):
    return _successful(events)

def _successful(events: Iterable):
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

    events = all_shots(game)
    events = _for_team(events, team_id)
    #events = _onnet(events)
    #events = _slot(events)
    #events = _deflected(events)
    #events = _successful(events)
    #events = _outside(events)
    print(len(events))

    events = all_shots(game)
    events = _for_team(events, team_id)
    events = _inner_slot(events, raw)  # lazy: loads playsequence.json on first call
    print(len(events))

