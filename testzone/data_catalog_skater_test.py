from __future__ import annotations
from collections.abc import Iterable
from pathlib import Path
import warnings
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, fields
import hockey.db.database as database
from hockey.io.raw_game import RawGame
from hockey.model.events import Event
from hockey.model.roster import Player, Roster
from hockey.model.toi import ToIInterval
from hockey.derive import context_filter as ctx
from hockey.derive.scoring import scoring
from hockey.derive.shooting import metrics as shooting
from hockey.db.database import open_database_azure
from hockey.db.event_query import query_events
from hockey.db.shift_query import query_shifts
from hockey.normalize.build_game import build_game
from hockey.normalize.build_game_db import build_game_from_db
from hockey.catalog.data_catalog import DataCatalog
from hockey.config.settings import Settings
settings = Settings.from_env(project_root=Path(__file__).resolve().parents[2])

if __name__ == "__main__":
    GAME_IDS = [186449, 186461]
    PLAYER_ID = 6970
    catalog = DataCatalog(settings.data_root_dir)
    games = catalog.season_schedule(17,"20252026")
    game_ids = [g['id'] for g in games['games']]

    conn = open_database_azure()
    cursor = conn.cursor()
    for game_id in game_ids:
        print(game_id)
        cursor.execute(
            f"""
            SELECT g.id
            FROM game g
            WHERE g.sl_id = {game_id};
            """
        )
        a=cursor.fetchall()
        id = a[0][0]
        d=database.create_map('player', cursor)
        print("apa")



       # game = build_game_from_db(game_id, conn)
    print("apa")
