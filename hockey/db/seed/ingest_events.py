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
import numpy as np
from hockey.model.game import Game
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import  build_game
from hockey.normalize.team_resolution import TeamResolver

__all__ = [
    'settings',
]

def ingest_events(game: Game):
    db = database.open_database()
    cursor = db.cursor()
    player_map = database.create_map('player', cursor)
    team_map = database.create_map('team', cursor)
    game_map = database.create_map('game', cursor, [game.info.game_id])
    resolver = TeamResolver.from_game_info(game.info)
    team_map = {resolver.home_display: team_map[resolver.home_id],
                resolver.away_display: team_map[resolver.away_id]}


    df = game.events_supplier_df()
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)

    # Substitute sportlogiq-id for players for database player_id
    # We need to do this slightly different for:
    # 1. list of sl_ids (defencemen and forwards) and
    # 2. single sl_ids (goalies and the player for the event).
    list_player_cols= ['team_forwards_on_ice_refs',
                       'opposing_team_forwards_on_ice_refs',
                       'team_defencemen_on_ice_refs',
                       'opposing_team_defencemen_on_ice_refs'
                       ]
    single_value_cols = ['team_goalie_on_ice_ref',
                         'opposing_team_goalie_on_ice_ref',
                         'player_reference_id']
    # For each column, replace None with empty string if the value is None
    # Each item in the lists are subsituted with the player-mapped value.
    for col in list_player_cols:
        df[col] = df[col].fillna('').apply(
            lambda x: ', '.join(str(player_map.get(int(k))) for k in x if len(k) > 0) if x else ''
        )

    # Substitute the single sl player-id with player-mapped value
    for col in single_value_cols:
        df[col] = df[col].fillna('').apply(lambda x: str(player_map.get(int(x))) if x else None)

    # For flags (which is a list of strings) we turn the list into a string ['xxx', 'yyy'] => 'xxx, yyy'
    # We do this to avoid storing lists in mysql
    df['flags'] = df['flags'].fillna('').apply(lambda x: ', '.join(x) if x else '')
    df['team'] = df['team'].fillna('').apply(lambda x: team_map.get(x) if x else None)
    #df['game_id'] = df['game_id'].fillna('').apply(lambda x: game_map.get(x) if x else None)
    df['team_in_possession'] = df['team_in_possession'].fillna('').apply(lambda x: team_map.get(x) if x else None)
    df.insert(0, "game_id", [game_map.get(e.game_id) for e in game.events])
    columns = database.get_table_columns('event', cursor)
    df.drop([c for c in df.columns if c not in columns], axis='columns', inplace=True)
    engine = create_engine(
        "mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3"
    )
    #df = clean_df(df)
    df.to_sql('event', engine, if_exists='append', index=False)


if __name__ == "__main__":
    # TODO: Replace with your Azure tenant ID
    raw = RawGame(game_id=202403, root_dir=settings.data_root_dir)
    game = build_game(raw)
    ingest_events(game)
