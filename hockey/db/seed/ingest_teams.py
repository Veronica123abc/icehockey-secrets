import struct
from azure.identity import InteractiveBrowserCredential
from typing import List, Dict
from hockey.db import database
from hockey.config.settings import Settings
from pathlib import Path
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
from tqdm import tqdm

def get_azure_sql_token(tenant_id: str = None):
    """Get Azure AD access token for SQL Database."""
    credential = InteractiveBrowserCredential(tenant_id=tenant_id)
    token = credential.get_token("https://database.windows.net/.default")

    # Convert token to the format pyodbc expects
    token_bytes = token.token.encode("utf-16-le")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
    return token_struct

def get_table_columns(cursor, table_name):
    """Get list of column names for a table."""
    cursor.execute(f"DESCRIBE {table_name}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns

def ingest_teams(teams: List[Dict]):
    """
    Ingest league JSON records into the Azure SQL 'league' table.

    Args:
        league_records: List of dicts with keys 'id' and 'name'
        connection_string: Azure SQL connection string
        tenant_id: Azure tenant ID (optional)
    """

    #db = database.open_database()
    db = database.open_database_azure()
    cursor = db.cursor()
    ctr=0

    columns = get_table_columns(cursor, 'team')

    columns = [
        'league_id',
        'name',
        'location',
        'logo_source',
        'shorthand',
        'display_name',
        'default_venue_id',
        'past_team_id',
        'sl_id'
    ]
    cols = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))

    for team in tqdm(teams):
        values = [
            team['leagueId'], team['name'], team['location'], team['logoSource'], team['shorthand'], team['displayName'], team['defaultVenueId'], team['pastTeamId'], team['id']
        ]
        try:
            updates = ', '.join(f"{col}=VALUES({col})" for col in columns if col != 'id')
            sql = f"INSERT INTO team ({cols}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
            cursor.execute(sql, tuple(values))
        except Exception as e:
            print(f"Error inserting league records: {e}")
            ctr += 1
    db.commit()
    print(f"Successfully inserted {len(teams) - ctr} teams")
    cursor.close()



if __name__ == "__main__":
    from hockey.catalog import DataCatalog
    LEAGUE_ID = 39
    SEASON = "20252026"

    catalog = DataCatalog(settings.data_root_dir)
    ingest_teams(catalog.teams())
    #ingest_teams(catalog.season_teams(LEAGUE_ID, SEASON))