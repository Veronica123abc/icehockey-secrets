from __future__ import annotations
import os, psutil
import sys
import pathlib
from pathlib import Path
import pandas as pd
from typing import Callable
from functools import partial
import json
from tqdm import tqdm
from typing import Any, Optional, TYPE_CHECKING
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from collections import defaultdict
from hockey.io.raw_competition import RawCompetition
from hockey.normalize.build_game import  build_game
from hockey.normalize.build_competition import build_competition
DFFilter = Callable[[pd.DataFrame], pd.DataFrame]
import time
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def filter_baseline_5v5(df_raw: pd.DataFrame) -> pd.DataFrame:
    return df_raw[(df_raw["team_skaters_on_ice"] == 5) &
                  (df_raw["opposing_team_skaters_on_ice"] == 5)]


def filter_abc_5v5(df_raw: pd.DataFrame, grades: Optional[set([str])]={"A","B","C"}) -> pd.DataFrame:
    return df_raw[(df_raw["expected_goals_all_shots_grade"].isin (["A","B","C"])) &
                  (df_raw["team_skaters_on_ice"] == 5) &
                  (df_raw["opposing_team_skaters_on_ice"] == 5)]

def filter_goal_5v5(df_raw: pd.DataFrame) -> pd.DataFrame:
    return df_raw[(df_raw["shorthand"].isin (["GOAL"])) &
                  (df_raw["team_skaters_on_ice"] == 5) &
                  (df_raw["opposing_team_skaters_on_ice"] == 5)]

def baseline_5v5_regulation(game_ids: Optional[list[int]] = []):
    accumulated_values = defaultdict(lambda: [])
    for game_id in tqdm(game_ids):
        raw = RawGame(game_id=game_id, root_dir=settings.data_root_dir)
        game = build_game(raw)
        times = game.shift_toi_series(start_time=0, end_time=3600, include_goalies=False,reset_on_whistle=True)
        time_diff = [t[game.info.home_team.id]['total_team_shift_toi'] / len(t[game.info.home_team.id]['players']) -
                     t[game.info.away_team.id]['total_team_shift_toi'] / len(t[game.info.away_team.id]['players'])
                     for t in times if len(t[game.info.home_team.id]['players']) == 5 and
                                       len(t[game.info.away_team.id]['players']) == 5]
        time_diff_home_team = time_diff
        time_diff_away_team = [-d for d in time_diff_home_team]
        accumulated_values[game.info.home_team.id] += time_diff_home_team
        accumulated_values[game.info.away_team.id] += time_diff_away_team
    return accumulated_values

def add_baseline_5v5(event_diff: dict, baseline:dict)->dict:
    e_d = event_diff.copy()
    for k, v in event_diff.items():
        if k not in baseline:
            continue
        e_d[k]["baseline"] = baseline[k]
    return e_d


def toi_difference(game_ids: list[int] = [], filter_func: Optional[DFFilter] = filter_goal_5v5):
    accumulated = defaultdict(lambda: {"for": [], "against": [], "baseline": []})
    for game_id in tqdm(game_ids):
        raw = RawGame(game_id=game_id, root_dir=settings.data_root_dir)
        game = build_game(raw)
        df_raw = game.events_raw_df()
        df_raw = filter_func(df_raw)
        times = [game.current_shift_toi(t) for t in df_raw['game_time']]
        time_diff = [t[game.info.home_team.id]['total_team_shift_toi'] / len(t[game.info.home_team.id]['players'])-
                     t[game.info.away_team.id]['total_team_shift_toi'] / len(t[game.info.away_team.id]['players'])
                     for t in times]

        df_raw.insert(0, "time_diff", time_diff, True)
        df_home_chances = df_raw[df_raw["team_id_in_possession"] == game.info.home_team.id][['time_diff', 'game_time', 'team_id_in_possession', 'team_skaters_on_ice', 'opposing_team_skaters_on_ice', 'expected_goals_all_shots_grade']]
        df_away_chances = df_raw[df_raw["team_id_in_possession"] == game.info.away_team.id][['time_diff', 'game_time', 'team_id_in_possession', 'team_skaters_on_ice', 'opposing_team_skaters_on_ice', 'expected_goals_all_shots_grade']]

        df_home_chances = df_home_chances.to_dict(orient="records")
        df_away_chances = df_away_chances.to_dict(orient="records")
        df_home_chances_against = df_away_chances
        df_away_chances_against = df_home_chances

        home_team = [c['time_diff'] for c in df_home_chances]
        home_team_against = [c['time_diff'] for c in df_home_chances_against]
        away_team = [-c['time_diff'] for c in df_away_chances]
        away_team_against = [-c['time_diff'] for c in df_away_chances_against]

        accumulated[game.info.home_team.id]['for'] += home_team
        accumulated[game.info.home_team.id]['against'] += home_team_against
        accumulated[game.info.away_team.id]['for'] += away_team
        accumulated[game.info.away_team.id]['against'] += away_team_against

        #Compute baselines
        #t0 = time.time()
        times = game.shift_toi_series(start_time=0, end_time=3600, include_goalies=False, reset_on_whistle=True)
        time_diff = [t[game.info.home_team.id]['total_team_shift_toi'] / len(t[game.info.home_team.id]['players']) -
                     t[game.info.away_team.id]['total_team_shift_toi'] / len(t[game.info.away_team.id]['players'])
                     for t in times if len(t[game.info.home_team.id]['players']) == 5 and
                     len(t[game.info.away_team.id]['players']) == 5]
        time_diff_home_team = time_diff
        time_diff_away_team = [-d for d in time_diff_home_team]
        accumulated[game.info.home_team.id]['baseline'] += time_diff_home_team
        accumulated[game.info.away_team.id]['baseline'] += time_diff_away_team
        #print(time.time() - t0)
        # process = psutil.Process(os.getpid())
        # print(process.memory_info().rss / 1e6, "MB")
    return accumulated


def get_games(filepath:pathlib.PosixPath, teams:list=[])->list:
    games = json.load(open(os.path.join(filepath,'games.json')))
    if len(teams) > 0:
        teams = [str(t) for t in teams] # in case team is passed as int
        games = [int(g["id"]) for g in games["games"] if g['home_team_id'] in teams or g['away_team_id'] in teams]
    else:
        games = [int(g["id"]) for g in games["games"]]
    return games


def event_histograms(games: int,
               filter_func: Optional[DFFilter] =  None
               )->dict:
    if not filter_func:
        print("No filter function was provided - using filter_abc_5v5")
        filter_func = partial(filter_abc_5v5, grades={"A", "B", "C"})
    toi_events = toi_difference(games[:], filter_func)
    #toi_baseline = baseline_5v5_regulation(games[:])
    #res = add_baseline_5v5(toi_events, toi_baseline)
    return toi_events #res

if __name__ == "__main__":
    league_id = "13"
    season = "20242025"
    stage = "regular"

    raw_competition = RawCompetition(int(league_id), root_dir=settings.data_root_dir)
    raw_competition.load()
    #competition = build_competition(raw_competition)
    games = raw_competition.game_ids(season, stage)

    #outfile = settings.output_path(f"abc_chances_5v5_{league_id}_{season}_{stage}.json")
    #filter_func = partial(filter_abc_5v5, grades={"A", "B", "C"})
    filter_func = partial(filter_goal_5v5) #, grades={"A", "B", "C"})
    stats = event_histograms(games[:1], filter_func)
    outfile = settings.output_path(f"{filter_func.func.__name__}_{league_id}_{season}_{stage}_test.json")
    outpath = settings.output_path(outfile)
    json.dump(stats, open(outpath, 'w'), indent=4)
