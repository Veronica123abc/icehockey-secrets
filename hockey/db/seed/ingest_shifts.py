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
    if df.empty:
        cursor.close()
        db.close()
        return df
    game_db_id = game_map.get(game.game_id)
    if game_db_id is None:
        raise ValueError(
            f"Game {game.game_id} not in DB -- run ingest_game first.")

    df.player_id = df.player_id.map(player_map)
    df.game_id = df.game_id.map(game_map)
    # A player the `player` table does not know cannot be referenced -- the
    # foreign key would reject the row, and the batch with it.
    unknown = df.player_id.isna()
    if unknown.any():
        print(f"Skipping {int(unknown.sum())} shifts of players missing from "
              f"`player`; run ingest_players first")
        df = df[~unknown]
        if df.empty:
            cursor.close()
            db.close()
            return df

    # Shifts this game already has in the table are dropped rather than
    # re-inserted: `to_sql(if_exists='append')` is one batch, so a single
    # duplicate would otherwise take the whole game down with it.
    existing = database.existing_shift_keys(game_db_id, cursor)
    keep = [database.shift_key(r.player_id, r.in_time, r.out_time) not in existing
            for r in df.itertuples()]
    if not all(keep):
        print(f"Skipping {len(df) - sum(keep)} shifts already in `shift` "
              f"for game {game.game_id}")
    df = df[keep]
    cursor.close()
    db.close()
    return df

def normalize_df(df):
    return df

def ingest_shifts(game:Game):
    df = create_dataframe(game)
    df = normalize_df(df)
    # engine = create_engine(
    #     "mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3"
    # )
    if df.empty:
        return
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