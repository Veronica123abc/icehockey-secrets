#!/usr/bin/python
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable
from xxlimited import Str

from hockey.model.events import Event
from hockey.data_collection.sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
import json
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

ALL_FLAGS = ['slapshot', 'firstafterpp', 'centerfodot', 'westofdot', 'firstozreception',
             'backhandforehand', 'alongboards', 'crest', 'nzgreyarea', 'screened', 'weakside',
             'highleft', 'gwg', 'withfailedcyclepass', 'strongside', 'eastofdot', 'backhand',
             'withshotonnet', 'fanned', 'crossice', 'whistlebeforeexit', 'eastfodot', 'recovered',
             'eastside', 'westfodot', 'deflected', 'withplayafter', 'withcyclepass', 'westeast',
             'lowleft', 'soft', 'fivehole', 'quickrelease', 'lefthandedopponent', 'straight',
             '1timer', 'snapshot', 'forehandbackhand', 'eastwest', 'penaltyshot', 'withshotonnetwhistle',
             'lowright', 'withrebound', 'midice', 'lowhigh', 'righthandedopponent', 'seam', 'westside',
             'wristshot', 'withpressure', 'wraparound', 'withslotshot', 'highdangermissedshotrecovery',
             'rim', 'withgoal', 'highright']

data_root_dir = settings.data_root_dir
ALL_FLAGS = json.load(open(data_root_dir / 'flag_definitions.json'))


class EventFilter(object):
    def __init__(self, settings: Settings):
        self.settings = settings

    def successful(self, events: Iterable[Event]) -> Iterable[Event]:
        return [event for event in events if event.outcome == 'successful']

    def failed(self, events: Iterable[Event]) -> Iterable[Event]:
        return [event for event in events if event.outcome == 'failed']

    def with_flags(self, events: Iterable[Event], flags: str | Iterable[str]) -> Iterable[Event]:
        if isinstance(flags, str):
            flags = [flags]
        for flag in flags:
            events = [event for event in events if flag in event.flags]
        return events

    def with_types(self, events: Iterable[Event], event_types: Iterable[str] | str) -> Iterable[Event]:
        if isinstance(event_types, str):
            event_types = [type]
        for event_type in event_types:
            events = [event for event in events if event_type in event.type]
        return events

    def for_team(self, events: Iterable[Event], team_id: int | str) -> Iterable[Event]:
        team_id = int(team_id)
        return [event for event in events if event.team_id == team_id]



if __name__ == "__main__":
    settings = Settings.from_env()
    catalog = DataCatalog(settings.data_root_dir)
    game_ids = catalog.scheduled_game_ids(17,"20252026")
    cf = EventFilter(settings)
    res = []
    for game_id in game_ids[:50]:
        print(game_id)
        raw_game = RawGame(game_id, settings.data_root_dir)
        game = build_game(raw_game)
        r = cf.with_types(game.events, ["d2d","offboards"])
        r2 = cf.with_flags(game.events, "lowhigh")
        for event in game.events:
            #res += event.flags
            res.append(event.type)
        res = list(set(res))
        print(len(res))
    game_ids = catalog.scheduled_game_ids(1,"20252026")
    for game_id in game_ids[:50]:
        print(game_id)
        raw_game = RawGame(game_id, settings.data_root_dir)
        game = build_game(raw_game)
        for event in game.events:
            #res += event.flags
            res.append(event.type)
        res = list(set(res))
        print(len(res))
    print(res)
