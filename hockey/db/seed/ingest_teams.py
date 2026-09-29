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

    # The supplier sends more than the schema keeps. v1 stored league_id,
    # logo_source, shorthand, display_name, default_venue_id and past_team_id;
    # v2's `team` is just id, sl_id, name and location. Intersecting with the
    # live table rather than hard-coding either list keeps this working across
    # a schema change instead of failing on the first INSERT.
    table_columns = set(get_table_columns(cursor, 'team'))
    supplied = {
        'league_id':        'leagueId',
        'name':             'name',
        'location':         'location',
        'logo_source':      'logoSource',
        'shorthand':        'shorthand',
        'display_name':     'displayName',
        'default_venue_id': 'defaultVenueId',
        'past_team_id':     'pastTeamId',
        'sl_id':            'id',
    }
    dropped = sorted(set(supplied) - table_columns)
    columns = [c for c in supplied if c in table_columns]
    if dropped:
        print(f"  not columns of `team` in this schema, not written: "
              f"{', '.join(dropped)}")
    cols = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))

    for team in tqdm(teams):
        values = [team[supplied[c]] for c in columns]
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
    LEAGUE_ID = 17

    # One league's clubs, not all 2395: `team` is referenced by foreign key
    # from `game`, so it only has to hold the teams whose games are loaded.
    # catalog.teams() is the whole file if you do want everything.
    catalog = DataCatalog(settings.data_root_dir)
    ingest_teams(catalog.league_teams(LEAGUE_ID))