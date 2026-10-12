from hockey.db import database
from hockey.config.settings import Settings
from pathlib import Path
from tqdm import tqdm
from hockey.helpers.pretty_print import *
from datetime import datetime

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]

def get_table_columns(cursor, table_name):
    """Get list of column names for a table."""
    cursor.execute(f"DESCRIBE {table_name}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns



def ingest_game(games):
    """Insert or update one season's schedule.

    THE SUPPLIER SENDS MORE THAN THE SCHEMA KEEPS. v1 stored venue_id,
    sl_reference_id, sl_reference_name, scheduled_venue_time and
    last_metrics_full_process_time; v2 deliberately does not. Rather than
    hard-coding either list, the record is intersected with the live table's
    own columns and the dropped names are reported once -- so this keeps
    working across a schema change instead of failing on the first INSERT.
    """
    db = database.open_database_azure()
    cursor = db.cursor()
    table_columns = set(get_table_columns(cursor, 'game'))
    team_map = database.create_map('team', cursor)
    league_map = database.create_map('league', cursor)
    league_id = league_map[int(games['competition_id'])]
    season = games['season']
    error_ctr = 0
    skipped_teams: set[int] = set()
    dropped_fields: set[str] = set()
    for record in tqdm(games['games']):
        # A team the `team` table does not know cannot be referenced -- the
        # foreign key would reject it. Skip the game and name the team, rather
        # than dying on a KeyError partway through the season.
        unknown = [int(record[k]) for k in ('home_team_id', 'away_team_id')
                   if int(record[k]) not in team_map]
        if unknown:
            skipped_teams.update(unknown)
            error_ctr += 1
            continue

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
            'last_metrics_full_process_time': None if not record['last_metrics_full_process_time'] else datetime.fromisoformat(record['last_metrics_full_process_time'].replace('Z', '+00:00')),
            'home_team_goals': record['score'][record['home_team_id']] if record['score'] else None,
            'away_team_goals': record['score'][record['away_team_id']] if record['score'] else None,
        }
        dropped_fields.update(k for k in record_data if k not in table_columns)
        record_data = {k: v for k, v in record_data.items() if k in table_columns}
        try:
            cols = ', '.join(record_data.keys())
            placeholders = ', '.join(['%s'] * len(record_data))
            updates = ', '.join(f"{col}=VALUES({col})" for col in record_data if col != 'id')
            sql = f"INSERT INTO game ({cols}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
            cursor.execute(sql, tuple(record_data.values()))
        except Exception as e:
            err(f"Error inserting game record: {e}")
            error_ctr += 1

    if dropped_fields:
        warn(f"not columns of `game` in this schema, not written: "
             f"{', '.join(sorted(dropped_fields))}")
    if skipped_teams:
        err(f"{len(skipped_teams)} team(s) missing from the `team` table, so "
            f"their games were skipped: {sorted(skipped_teams)}. "
            f"Refresh teams.json and run ingest_teams.py first.")
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

    LEAGUE_ID = 1
    SEASON = "20262027"

    catalog = DataCatalog(settings.data_root_dir)
    games = catalog.season_schedule(LEAGUE_ID, SEASON)
    ingest_game(catalog.season_schedule(LEAGUE_ID, SEASON))
