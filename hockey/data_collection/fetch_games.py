
#!/usr/bin/python
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from hockey.data_collection import sportlogiq_api
from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
import requests
from tqdm import tqdm
import sportlogiq_api
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]

def find_incomplete_games(game_ids = None, check_shifts=True, save_to_file=None):
    #print(check_shifts)
    if game_ids is None:
        games = os.listdir(settings.data_root_dir)
        game_ids = [g for g in games if g.isnumeric() and os.path.isdir(settings.data_root_dir / str(g))]
    incomplete_games = []
    missing_period_times_in_shifts = []

    for game_id in tqdm(game_ids, desc="Verifying completeness ..."):
        filepath = settings.data_root_dir / str(game_id)
        if (os.path.exists(filepath) and os.path.isdir(filepath)):
            existing_files = [settings.data_root_dir / str(game_id) / f for f in os.listdir(filepath)]
            correct_existing_files = [f for f in existing_files if os.stat(f).st_size > 0]
            if len(correct_existing_files) != 6:
                incomplete_games.append(game_id)

    return incomplete_games

def find_missing_games(game_ids: list[int]):
    downloaded_games = [game_id for game_id in game_ids if os.path.exists(settings.data_root_dir / str(game_id))]
    missing_games = [g for g in game_ids if g not in downloaded_games]
    return missing_games

def find_games(league_id, seasons: list[str] = None):
    to_download = []
    if not seasons:
        season_items = json.load(open(settings.data_root_dir / 'all_competitions.json'))[str(league_id)]['seasons']
        seasons = [k['name'] for k in season_items]

    for season in seasons:
        game_file = settings.data_root_dir / 'leagues'/ f'{league_id}' / f'{season}' / 'games.json'
        #with open(game_file, "r") as f:
        games = json.load(open(game_file,"r"))
        game_ids = [g['id'] for g in games['games']]
        inc = find_incomplete_games(game_ids)
        miss = find_missing_games(game_ids)
    return inc+miss



def find_seasons(league_id):
    season_items = json.load(open(settings.data_root_dir / 'all_competitions.json'))[str(league_id)]['seasons']
    seasons = [k['name'] for k in season_items]
    return seasons


if __name__ == '__main__':
    #seasons = find_seasons(213)
    game_ids = find_games(213,['20242025'])
    sportlogiq_api.download_complete_games(game_ids=game_ids, verbose=True)

