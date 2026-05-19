import json
from typing import Dict
from hockey.db import database
from hockey.config.settings import Settings
from pathlib import Path

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
import pandas as pd
from sqlalchemy import create_engine
import numpy as np
from hockey.model.game import Game
__all__ = [
    'settings',
]

def extract_player_refs(events):
    goalie_fields = ['opposing_team_goalie_on_ice_ref', 'team_goalie_on_ice_ref']
    skater_fields = [
        'team_forwards_on_ice_refs',
        'opposing_team_forwards_on_ice_refs',
        'team_defencemen_on_ice_refs',
        'opposing_team_defencemen_on_ice_refs',
    ]
    player_ids = []
    for event in events['events']:
        for field in skater_fields:
            player_ids += event.get(field) if isinstance(event.get(field), list) else []
            player_ids = list(set(player_ids))

        for field in goalie_fields:
            if isinstance(event.get(field), int) and event.get(field) not in player_ids:
                player_ids.append(event.get(field))
    player_ids = [int(p) for p in player_ids]
    return player_ids



def validate_player_refs(events, player_map: Dict[str, str],):
    """Validate player references in events against provided player map."""
    goalie_fields = ['opposing_team_goalie_on_ice_ref', 'team_goalie_on_ice_ref']
    skater_fields = [
        'team_forwards_on_ice_refs',
        'opposing_team_forwards_on_ice_refs',
        'team_defencemen_on_ice_refs',
        'opposing_team_defencemen_on_ice_refs',
    ]
    player_ids = []
    for event in events['events']:
        for field in skater_fields:
            player_ids += event.get(field) if isinstance(event.get(field), list) else []
            player_ids = list(set(player_ids))

        for field in goalie_fields:
            if isinstance(event.get(field), int) and event.get(field) not in player_ids:
                player_ids.append(event.get(field))
    player_ids = [int(p) for p in player_ids]
    missing_player_ids = [p for p in player_ids if p not in player_map]
    return missing_player_ids



def get_table_columns(cursor, table_name):
    """Get list of column names for a table."""
    cursor.execute(f"DESCRIBE {table_name}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns

def normalize_events(cursor, player_map, events):

    # Create map from sl-style team names to id
    sql = f"select id, location, name from team;"
    cursor.execute(sql)
    teams = cursor.fetchall()
    team_name_map = {team[1] + ' ' + team[2]: int(team[0]) for team in teams}
    goalie_fields = ['opposing_team_goalie_on_ice_ref', 'team_goalie_on_ice_ref']
    skater_fields = [
        'team_forwards_on_ice_refs',
        'opposing_team_forwards_on_ice_refs',
        'team_defencemen_on_ice_refs',
        'opposing_team_defencemen_on_ice_refs',
    ]
    # fetch game_id
    sql = f"select id from game where sl_id={events['id']};"
    try:
        cursor.execute(sql)
        game_id = int(cursor.fetchone()[0])
    except Exception as e:
        print(f"Error fetching game ID: {e}")
        return

    normalized_events = []
    for event in events['events']:
        # Add game_id to event
        event['game_id'] = game_id

        # Substitute team names to team ids
        if event['team_in_possession'] not in [None, 'None', 'null']:
            event['team_in_possession'] = team_name_map[event['team_in_possession']]
        if event['team'] not in [None, 'None', 'null']:
            event['team'] = team_name_map[event['team']]
        print(event['team_in_possession'])
        print(event['team'])
        # Substitute list of sl playernames to string of list of player ids
        for field in skater_fields:
            ref = event.get(field)
            event[field] = str([player_map.get(int(r)) for r in ref]) if ref else None

        # Substitute goalies sl-ids with player ids.
        for field in goalie_fields:
            ref = event.get(field)
            event[field] = player_map.get(int(ref)) if ref else None

        #Change flags to string
        event['flags'] = str(event['flags'])

        #convert expected goals to float or 0
        float_items = ["expected_goals_on_net", "expected_goals_all_shots"]
        for item in float_items:
            event[item] = float(event.get(item)) if len(event.get(item))>0 else 0

        normalized_events.append(event)
    events['events'] = normalized_events
    return events

def clean_df(df):
    # Step 1: Replace empty strings and 'none' strings with NaN
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)

    # Step 2: Convert numeric columns to proper types (handles NaN automatically)
    numeric_columns = [
        'period', 'period_time', 'game_time', 'frame',
        'x_coord', 'y_coord', 'x_adj_coord', 'y_adj_coord',
        'score_differential', 'team_skaters_on_ice', 'opposing_team_skaters_on_ice',
        'expected_goals_on_net', 'expected_goals_all_shots',
        'team_goalie_on_ice_ref', 'opposing_team_goalie_on_ice_ref'
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')  # Converts invalid values to NaN

    # Step 3: Replace NaN with None for SQL NULL (optional but recommended)
    df = df.where(pd.notnull(df), None)
    return df

def create_dataframe(game:Game) -> pd.DataFrame:

    df = pd.DataFrame(game.events_raw_df)
    df = clean_df(df)
    return df



def ingest_events(events):

    db = database.open_database()
    cursor = db.cursor()
    player_map = database.create_map('player', cursor)
    missing_player_ids = validate_player_refs(events, player_map)
    if len(missing_player_ids) > 0:
        raise ValueError(f"Missing player IDs: {missing_player_ids}")

    events = normalize_events(cursor, player_map, events)
    df = pd.DataFrame(events['events'])
    columns = database.get_table_columns('event', cursor)
    df.drop([c for c in df.columns if c not in columns], axis='columns', inplace=True)
    # engine = create_engine(
    #     f"mysql+mysqlconnector://mysqladmin:B1llyfjant.1@mysql-flex-public.mysql.database.azure.com:3306/your_database",
    #     connect_args={"ssl_ca": "~/DigiCertGlobalRootCA.crt.pem"}
    # )
    engine = create_engine(
        "mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3"
    )
    df = clean_df(df)
    df.to_sql('event', engine, if_exists='append', index=False)



if __name__ == "__main__":
    # TODO: Replace with your Azure tenant ID

    #leagues = json.load(open("/home/veronica/hockeystats/ver3/leagues/leagues.json", "r"))
    events = json.load(open(settings.data_root_dir / '202401' / 'playsequence.json' ))
    events2 = json.load(open(settings.data_root_dir / '202401' / 'playsequence_compiled.json'))
    ingest_events(events)