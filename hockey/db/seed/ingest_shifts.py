from hockey.db import database
from pathlib import Path
from hockey.config.settings import Settings
from hockey.normalize.build_game import  build_game
from hockey.model.game import Game
import pandas as pd

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def create_dataframe(game:Game):
    db = database.open_database_azure()
    cursor = db.cursor()
    records = [
        {
            'player_id': toi.player_id,
            'game_id': toi.game_id,
            'in_time': toi.start_t,
            'out_time': toi.end_t
        }
        for toi in game.toi
    ]
    players = game.roster.players.keys()
    game_map = database.create_map('game', cursor=cursor, values=[game.game_id])
    player_map = database.create_map('player', cursor=cursor, values=players)

    df = pd.DataFrame(records)
    df.player_id = df.player_id.map(player_map)
    df.game_id = df.game_id.map(game_map)
    return df

def normalize_df(df):
    return df

def ingest_shifts(game:Game):
    df = create_dataframe(game)
    df = normalize_df(df)
    # engine = create_engine(
    #     "mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3"
    # )
    engine = database.sqlalchemy_engine_azure()
    df.to_sql('shift', engine, if_exists='append', index=False)


if __name__ == "__main__":
    from hockey.catalog import DataCatalog

    LEAGUE_ID = 213
    SEASON = "20242025"

    catalog = DataCatalog(settings.data_root_dir)
    for game_id in catalog.scheduled_game_ids(LEAGUE_ID, SEASON):
        try:
            game = build_game(catalog.raw_game(game_id))
            ingest_shifts(game)
        except Exception as e:
            print(f"Skipping game {game_id}: {e}")