from __future__ import annotations
from pathlib import Path
from hockey.model.game import Game
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
import os
import sys
import json
import matplotlib.pyplot as plt
from tqdm import tqdm
from typing import Any, Optional, TYPE_CHECKING


from hockey.io.raw_game import RawGame
from shifts import toi_status


def fatigued_ABC(game_ids: list[int] = [168742]):
    accumulated = {}


    for game_id in tqdm(game_ids):
        #print(game_id)
        raw = RawGame(game_id=game_id, root_dir=Path("/home/veronica/hockeystats/ver3/"))
        game = build_game(raw)
        df_raw = game.events_raw_df()
        df_raw = df_raw[df_raw["expected_goals_all_shots_grade"].isin (["A","B","C"])]
        df_raw = df_raw[df_raw["team_skaters_on_ice"] == 5]
        df_raw = df_raw[df_raw["opposing_team_skaters_on_ice"] == 5]
        times = [game.current_shift_toi(t) for t in df_raw['game_time']]
        time_diff = [times[i][game.info.home_team.id]['total_team_shift_toi'] -
                     times[i][game.info.away_team.id]['total_team_shift_toi'] for i in range(len(times))]
        df_raw.insert(0, "time_diff", time_diff, True)

        df_home_chances = df_raw[df_raw["team_id_in_possession"] == game.info.home_team.id][['time_diff', 'game_time', 'team_id_in_possession', 'team_skaters_on_ice', 'opposing_team_skaters_on_ice', 'expected_goals_all_shots_grade']]
        df_away_chances = df_raw[df_raw["team_id_in_possession"] == game.info.away_team.id][['time_diff', 'game_time', 'team_id_in_possession', 'team_skaters_on_ice', 'opposing_team_skaters_on_ice', 'expected_goals_all_shots_grade']]

        df_home_chances = df_home_chances.to_dict(orient="records")
        df_away_chances = df_away_chances.to_dict(orient="records")

        home_team = [round(c['time_diff'], 2) for c in df_home_chances]
        away_team = [round(-c['time_diff'], 2) for c in df_away_chances]



        if game.info.home_team.id not in list(accumulated.keys()):
            accumulated[game.info.home_team.id] = home_team
        else:
            accumulated[game.info.home_team.id] += home_team

        if game.info.away_team.id not in list(accumulated.keys()):
            accumulated[game.info.away_team.id] = away_team
        else:
            accumulated[game.info.away_team.id] += away_team



    return accumulated


def get_games(filepath):
    games = json.load(open(os.path.join(filepath,'games.json')))
    games = [int(g["id"]) for g in games["games"]]
    return games

if __name__ == "__main__":
    #games = os.listdir("/home/veronica/hockeystats/ver3/")
    #games = [g for g in games if g.isdigit()]
    #games = [int(g) for g in games]

    games = get_games("/home/veronica/hockeystats/ver3/leagues/13/20242025/regular")
    script_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
    res = fatigued_ABC(games[0:])
    json.dump(res, open('fatigued_0.json', 'w'), indent=4)
    teams = list(res.keys())

    plt.hist(res[teams[0]], bins=20)
    plt.xlabel('time diff')
    plt.ylabel('#')
    plt.show()

