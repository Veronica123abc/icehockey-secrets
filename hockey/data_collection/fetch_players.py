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

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]


def download_players(conn: SportlogiqApi=None, leagues_filter: list[int]=None, season_filter: list[str]=None):
    updated_from = '2000-01-01T12:12:30.000Z'
    if not conn:
        conn = SportlogiqApi()
    leagues = os.listdir(settings.data_root_dir / 'leagues')
    leagues = [l for l in leagues if l.isnumeric()]
    if leagues_filter:
        leagues = [l for l in leagues if int(l) in leagues_filter]
    for league in leagues:
        competitions_path = settings.data_root_dir / 'leagues' / f"{league}" / "competitions.json"
        competitions = json.load(open(competitions_path, "r"))
        seasons = [season['name'] for season in competitions['seasons']]
        if season_filter:
            seasons = [season for season in seasons if season in season_filter]
        for season in seasons:
            print(f"Downloading players from league {league} during season {season}")
            try:
                data = conn.req.get(conn.apiurl + f'/v1/hockey/players?season={season}&competition_id={league}')
                with open(settings.data_root_dir / 'leagues' / league / season / f'players.json', "w") as f:
                    json.dump(data.json(), f, indent=4)
            except:
                print(f"Failed to download players from league {league} during season {season}")


if __name__ == "__main__":
    download_players(leagues_filter=[213], season_filter=['20242025'])