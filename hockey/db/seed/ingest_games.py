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
from hockey.io.raw_competition import RawCompetition
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



def ingest_participation(cursor, league_id: int, season: str, team_map: dict, games: list) -> None:
    seen = set()
    for record in games:
        for sl_team_id in (int(record['home_team_id']), int(record['away_team_id'])):
            if sl_team_id in seen:
                continue
            seen.add(sl_team_id)
            team_id = team_map.get(sl_team_id)
            if team_id is None:
                err(f"No team mapping for sl_team_id {sl_team_id}, skipping participation entry")
                continue
            cursor.execute(
                "INSERT IGNORE INTO participation (league_id, team_id, season, sl_team_id) "
                "VALUES (%s, %s, %s, %s)",
                (league_id, team_id, season, sl_team_id),
            )


def ingest_game(games):
    db = database.open_database_azure()
    cursor = db.cursor()
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
            'last_metrics_full_process_time': datetime.fromisoformat(record['last_metrics_full_process_time'].replace('Z', '+00:00')),
            'home_team_goals': record['score'][record['home_team_id']],
            'away_team_goals': record['score'][record['away_team_id']]
        }
        try:
            cols = ', '.join(record_data.keys())
            placeholders = ', '.join(['%s'] * len(record_data))
            sql = f"INSERT INTO game ({cols}) VALUES ({placeholders})"
            cursor.execute(sql, tuple(record_data.values()))
        except Exception as e:
            err(f"Error inserting game record: {e}")
            error_ctr += 1

    ingest_participation(cursor, league_id, season, team_map, games['games'])

    try:
        db.commit()
        ok(f"Successfully inserted {len(games['games']) - error_ctr} of {len(games['games'])} games")
    except Exception as e:
        err(f"Error committing records: {e}")
        raise
    finally:
        cursor.close()


if __name__ == "__main__":
    from hockey.catalog import DataCatalog

    LEAGUE_ID = 213
    SEASON = "20232024"

    catalog = DataCatalog(settings.data_root_dir)
    ingest_game(catalog.season_schedule(LEAGUE_ID, SEASON))
