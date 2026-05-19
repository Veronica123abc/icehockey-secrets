import struct
from azure.identity import InteractiveBrowserCredential
from hockey.db import database
from pathlib import Path
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import  build_game
from hockey.model.game import Game

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

def ingest_players(game:Game):
    """
    Ingest league JSON records into the Azure SQL 'league' table.

    Args:
        league_records: List of dicts with keys 'id' and 'name'
        connection_string: Azure SQL connection string
        tenant_id: Azure tenant ID (optional)
    """

    db = database.open_database()
    cursor = db.cursor()
    ctr=0

    for record in tqdm(players):
        try:
            sql = "INSERT INTO player (sl_id, first_name, last_name) VALUES (%s, %s, %s)"
            cursor.execute(sql, (int(record['id']), record['first_name'], record['last_name']))
        except Exception as e:
            print(f"Error inserting league records: {e}")
            ctr += 1
    db.commit()
    print(f"Successfully inserted {len(players) - ctr} players")
    cursor.close()



if __name__ == "__main__":

    raw = RawGame(game_id=202401, root_dir=settings.data_root_dir)
    game = build_game(raw)