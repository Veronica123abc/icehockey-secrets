import struct
from azure.identity import InteractiveBrowserCredential
import pyodbc
import json
from typing import List, Dict
import database
from hockey.config.settings import Settings
import pathlib
from pathlib import Path
from tqdm import tqdm
from hockey.helpers.pretty_print import *
from datetime import datetime
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
import pandas as pd
from sqlalchemy import create_engine
__all__ = [
    'settings',
]

def get_table_columns(cursor, table_name):
    """Get list of column names for a table."""
    cursor.execute(f"DESCRIBE {table_name}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns



def ingest_game(games):
    db = database.open_database()
    cursor = db.cursor()
    #columns = ['id', 'home_team', 'away_team', 'score', 'date']  # your actual column names
    #columns = get_table_columns(cursor, 'game')
    team_map = database.create_map('team', cursor)
    league_map = database.create_map('league', cursor)
    league_id = league_map[int(games['competition_id'])]
    season = games['season']
    error_ctr = 0
    for record in tqdm(games['games']):
        record_data = {
            'sl_id': record['id'],
            'home_team_id': team_map[int(record['home_team_id'])],
            'away_team_id': team_map[int(record['away_team_id'])],
            'league_id': league_id,
            'season': season,
            'stage': record['stage'],
            'scheduled_time': record['scheduled_time'],
            'scheduled_venue_time': record['scheduled_venue_time'],
            'venue_id': record['venue_id'],
            'event_status': record['event_status'],
            'sl_reference_id': record['reference_id'],
            'sl_reference_name': record['reference_name'],
            'last_metrics_full_process_time': datetime.fromisoformat(record['last_metrics_full_process_time'].replace('Z', '+00:00'))
        }
        try:
            # Build the SQL dynamically
            cols = ', '.join(record_data.keys())
            placeholders = ', '.join(['%s'] * len(record_data))
            sql = f"INSERT INTO game ({cols}) VALUES ({placeholders})"
            cursor.execute(sql, tuple(record_data.values()))
        except Exception as e:
            err(f"Error inserting game record: {e}")
            error_ctr += 1

    # Try to commit the staged changes to the database
    try:
        db.commit()
        ok(f"Successfully inserted {len(games['games']) - error_ctr} of "
           f"{len(games['games'])}record")
    except Exception as e:
        err(f"Error inserting game records: {e}")
        raise Exception(f"Error inserting {len(games['games']) - error_ctr} "
                          f"records into {len(games['games'])} records: {len(games['games'])} "
        )
    finally:
        cursor.close()


if __name__ == "__main__":
    # TODO: Replace with your Azure tenant ID

    #leagues = json.load(open("/home/veronica/hockeystats/ver3/leagues/leagues.json", "r"))
    game = json.load(open(settings.data_root_dir / 'leagues' / '13' / '20252026' / 'games.json' ))
    ingest_game(game)
