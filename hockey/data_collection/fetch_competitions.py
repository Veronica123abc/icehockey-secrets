import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pandas.io.common import file_exists

from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]

def download_competitions(league_id, conn=None):
    if not conn:
        conn = SportlogiqApi()
    try:
        print(f"Fetching competitions for league: {league_id}")
        data = conn.req.get(conn.apiurl + f"/v1/hockey/competitions/{league_id}")
    except Exception as e:
        print(f"Error fetching competitions for league {league_id}: {e}")
        return
    with open(settings.data_root_dir / 'leagues' / str(league_id) / "competitions.json", "w") as f:
        json.dump(data.json(), f, indent=4)

def update_all_competitions(league_ids: list[int|str]):
    all_competitions = {}
    league_ids = os.listdir(settings.data_root_dir / 'leagues')
    league_ids = [l for l in league_ids if l.isnumeric()]
    for league_id in league_ids:
        #check if file exists
        if file_exists(settings.data_root_dir / 'leagues' / str(league_id) / 'competitions.json'):
            all_competitions[league_id] = json.load(open(settings.data_root_dir / 'leagues' / str(league_id) / 'competitions.json'))
    with open(settings.data_root_dir / 'all_competitions.json', 'w') as f:
        json.dump(all_competitions, f, indent=4, sort_keys=True)


if __name__ == "__main__":
    # update_all_competitions([1,13,17,213])
    download_competitions(1)
    download_competitions(13)
    download_competitions(17)
    download_competitions(213)