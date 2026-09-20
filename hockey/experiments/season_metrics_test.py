from __future__ import annotations
import os
from pathlib import Path
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.derive.entries import zone_entries
from hockey.catalog import DataCatalog
from hockey.config.settings import Settings
from hockey.db.database import open_database_azure
from hockey.db.event_query import query_events

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
if __name__ == "__main__":
    league_id = 13
    season = '20252026'
    stage = 'regular'
    catalog = DataCatalog(settings.data_root_dir)
    games = catalog.scheduled_game_ids(int(league_id), season, stages=[stage])

    conn = open_database_azure()
    shots = query_events(conn,
                         season="20252026",
                         #names=["shot"],
                         on_ice_player_sl_id=29564,  # Dennis Fröland
                         team_sl_id=1395)  # MoDo Hockey
    print(len(shots))

    # GAME_ID = 54559
    # total_sum = 0
    # total = 0
    # for GAME_ID in games:
    #     #GAME_ID = 54559
    #     game = None