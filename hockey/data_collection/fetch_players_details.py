#!/usr/bin/python
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from hockey.catalog import DataCatalog
import requests
from hockey.config.settings import Settings
from hockey.data_collection.sportlogiq_api_v3 import SportlogiqApi
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
import uuid
def get_players(team_id,
                season,
                season_stage,
                catalog: DataCatalog,
                conn: SportlogiqApi=None
                ):

    if conn is None:
        conn = SportlogiqApi()

    season_id = int(season[4:]) - 2014
    url = f"/api/v3/players"
    params = {'teamid[]':team_id, 'seasonid[]':season_id, 'seasonstage[]':'regular'}
    url_players=conn.BASE_URL + f"/api/v3/players"
    res = conn.req.get(
        url_players, params=params, timeout=60
    )
    data = res.json()
    filename = uuid.uuid4().hex + '.json'
    catalog.save_players_detailed(data, filename)


if __name__ == "__main__":
    conn = SportlogiqApi()
    team_id=322
    season_id=10
    season='20252026'
    stage='regular'
    catalog = DataCatalog(settings.data_root_dir)
    games = get_players(team_id, season, stage, catalog, conn)
    games.json()
    print(games)
    print(games.json())