import struct
from azure.identity import InteractiveBrowserCredential
import pyodbc
import json
from typing import List, Dict
import database
from hockey.config.settings import Settings
import pathlib
from pathlib import Path
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def get_azure_sql_token(tenant_id: str = None):
    """Get Azure AD access token for SQL Database."""
    credential = InteractiveBrowserCredential(tenant_id=tenant_id)
    token = credential.get_token("https://database.windows.net/.default")

    # Convert token to the format pyodbc expects
    token_bytes = token.token.encode("utf-16-le")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
    return token_struct


def ingest_leagues(league_records: List[Dict]):
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
    try:
        for record in league_records:

            sql = "INSERT INTO league (sl_id, name, sl_name) VALUES (%s, %s, %s)"
            cursor.execute(sql, (int(record['id']), record['name'], record['name']))


        db.commit()
        print(f"Successfully inserted {len(league_records)} league records")

    except Exception as e:
        #cursor.rollback()
        print(f"Error inserting league records: {e}")
        raise

    finally:
        cursor.close()



if __name__ == "__main__":
    from hockey.catalog import DataCatalog

    catalog = DataCatalog(settings.data_root_dir)
    ingest_leagues(catalog.leagues())
