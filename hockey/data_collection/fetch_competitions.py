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

if __name__ == "__main__":
    download_competitions(1)
    download_competitions(13)
    download_competitions(17)
    download_competitions(213)