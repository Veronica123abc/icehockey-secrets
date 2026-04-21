#!/usr/bin/python
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]
def download_game_index(league_id, season, stage=None, conn=None):
    print(league_id, ' ', season, ' ', stage)
    ROOTPATH = settings.data_root_dir
    filepath = os.path.join(ROOTPATH, 'leagues', f"{league_id}", f"{season}")
    if stage:
        filepath = os.path.join(filepath, f"{stage}")
    if not (os.path.exists(filepath) and os.path.isdir(filepath)):
        os.makedirs(filepath)
    if conn is None:
        conn = SportlogiqApi()

    if not stage:
        data = conn.req.get(
            conn.apiurl + f"/v1/hockey/games?season={season}&competition_id={league_id}&withvidparams=true")
    else:
        data = conn.req.get(
            conn.apiurl + f"/v1/hockey/games?season={season}&stage={stage}&competition_id={league_id}&withvidparams=true")

    with open(f"{filepath}" + "/games.json", "w") as f:
        json.dump(data.json(), f, indent=4)

def download_all_game_indexes_per_season(league_id, conn=None):
    ROOTPATH = "/home/veronica/hockeystats/ver3"
    filepath = os.path.join(ROOTPATH, 'leagues', f"{league_id}", "competitions.json")
    competitions = json.load(open(filepath, "r"))
    conn = SportlogiqApi()
    for season in competitions['seasons']:
        print(f"Downloading {season['name']}")
        download_game_index(league_id, season['name'], conn=conn)

def download_all_game_indexes_per_stage(league_id):
    ROOTPATH = "/home/veronica/hockeystats/ver3"
    filepath = os.path.join(ROOTPATH, 'leagues', f"{league_id}", "competitions.json")
    competitions = json.load(open(filepath, "r"))
    conn = SportlogiqApi()
    for season in competitions['seasons']:
        for stage in season['stages']:
            print(f"Downloading {season['name']}_{stage['name']}")
            download_game_index(league_id, season['name'], stage['name'], conn=conn)


if __name__ == "__main__":
    download_all_game_indexes_per_season(1)
    download_all_game_indexes_per_season(13)
    download_all_game_indexes_per_season(17)
    download_all_game_indexes_per_season(213)
