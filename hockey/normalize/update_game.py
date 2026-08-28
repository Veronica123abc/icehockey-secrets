from __future__ import annotations
from hockey.io.raw_game import RawGame
from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.normalize.playsequence import normalize_playsequence
from hockey.normalize.player_toi import normalize_player_toi
from hockey.normalize.roster import normalize_roster
from hockey.normalize.team_resolution import TeamResolver
import time

def update_game(game: Game, raw_game: RawGame, columns: list[str]) -> Game:
    raw_events = raw_game.playsequence_raw

#def add_raw_base_events(all_events: Iterable[dict], events: Iterable[dict], raw_game: RawGame) -> Iterable[dict]:
    res = []
    #base_events = [e for e in game.events if '-' in e.get_raw('event_id')]

    events = game.events
    updated_events = []
    # for e in [event.raw for event in game.events if event.get_raw('team_in_possession') not in ['None', 'none', None]]:
    for e in events:
        for c in columns:
            c_val = raw_game.full_event_field_2(e.raw['current_possession'], e.raw['current_play_in_possession'], c)
            # print(c_val)#if e.get_raw('team_in_possession') not in ['None', 'none', None]:
            e.raw[c] = c_val[c] # raw_game.full_event_field_2(e.raw['current_possession'], e.raw['current_play_in_possession'], c)
        updated_events.append(e)
        # if '-' in e['event_id']:
        #     base_event_id = e['event_id'].split('-')[1]
        # else:
        #     base_event_id = e['event_id']
        # for c in columns:
        #     e[c] = raw_game.full_event_field_2(e['current_possession'], e['current_play_in_possession'], c)
        #res.append(e)
    game.events = updated_events
    return game