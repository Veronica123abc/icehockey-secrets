from __future__ import annotations
import pathlib
import os
from pathlib import Path
from itertools import chain
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from dataclasses import dataclass, field
from hockey.model.game import Game
from dataclasses import dataclass, field
from hockey.model.game import Game
#from hockey.derive.entries import zone_entries
from hockey.derive.OZEntries.entries import zone_entry_events, zone_entries
from hockey.catalog import DataCatalog
from hockey.config.settings import Settings
from hockey.derive.current_shift import current_shift_toi_series
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

'''
Check the current shift TOI difference at entries leading to a goal to see if fresh legs on entry
increases scoring rate. Results seem to confirm fresh team at entry scores better, but correlation is very weak.
'''


if __name__ == "__main__":
    league_id = 1
    season = '20252026'
    stage = 'regular'
    catalog = DataCatalog(settings.data_root_dir)
    games = catalog.scheduled_game_ids(int(league_id), season, stages=[stage])


    GAME_ID = 54559
    total_sum = 0
    total = 0
    negatives = 0
    for GAME_ID in games:
        #GAME_ID = 54559
        game = None
        root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
        raw = RawGame(game_id=GAME_ID, root_dir=root, playsequence_source="playsequence_compiled")
        game = build_game(raw)
        ht_id = game.info.home_team.id
        at_id = game.info.away_team.id


        # TOI DIFFERENCE FOR GOALS
        goal_events = [e for e in game.events if e.name == "goal"]
        goal_events = [e for e in goal_events if e.raw.get('team_skaters_on_ice') == 5 and
                       e.raw.get('opposing_team_skaters_on_ice') == 5]
        goal_events = sorted(goal_events, key=lambda e: e.t)
        goal_times = [e.t for e in goal_events]
        goal_toi = current_shift_toi_series(game, goal_times)
        goal_res = []

        for i in range(len(goal_events)):
            team = goal_events[i].team_id
            if team == ht_id:
                diff = goal_toi[i][ht_id]['average_team_shift_toi'] - goal_toi[i][at_id]['average_team_shift_toi']
            else:
                diff = goal_toi[i][at_id]['average_team_shift_toi'] - goal_toi[i][ht_id]['average_team_shift_toi']
            goal_res.append(diff)
        #print(goal_res)
        #print(goal_times)

        # TOI DIFFERENCE FOR ENTRIES WITH GOAL

        entries = zone_entries(game, faceoff_as_entry=False)
        ht_entries = [e for e in entries[ht_id] if e.goal > 0]
        at_entries = [e for e in entries[at_id] if e.goal > 0]
        entries = ht_entries + at_entries
        entries = sorted(entries, key=lambda e: e.entry_time)
        entry_goal_times = [e.entry_time + e.goal for e in entries]
        goals_without_entry_times = [t for t in goal_times if t not in entry_goal_times]
        # print(game.info.game_id, " ", goals_without_entry_times)

        goals_without_entry = [e for e in goal_events if e.t not in entry_goal_times]


        ENTRIES=True
        if (ENTRIES):
            times = [e.entry_time for e in entries]
            toi = current_shift_toi_series(game, times)
            res=[]
            for i in range(len(entries)):
                team = entries[i].team_id
                if team == ht_id:
                    diff = toi[i][ht_id]['average_team_shift_toi'] - toi[i][at_id]['average_team_shift_toi']
                else:
                    diff = toi[i][at_id]['average_team_shift_toi'] - toi[i][ht_id]['average_team_shift_toi']
                res.append(diff)
        else:
            scoped_events = goals_without_entry
            scoped_events = goal_events
            times = [e.t for e in scoped_events]
            toi = current_shift_toi_series(game, times)
            res=[]
            for i in range(len(scoped_events)):
                team = scoped_events[i].team_id
                if team == ht_id:
                    diff = toi[i][ht_id]['average_team_shift_toi'] - toi[i][at_id]['average_team_shift_toi']
                else:
                    diff = toi[i][at_id]['average_team_shift_toi'] - toi[i][ht_id]['average_team_shift_toi']
                res.append(diff)

        new_negatives = len([r for r in res if r == 0])

        total_sum += sum(res)
        total += len(res)
        negatives += new_negatives
        print(total_sum / total, " ", negatives, " of ", total, '(', negatives / total,  ' %)')
        print("end")