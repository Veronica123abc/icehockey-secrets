from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

import database
from hockey.config.settings import Settings
from hockey.model.game import Game
from hockey.normalize.build_game import build_game
from hockey.normalize.team_resolution import TeamResolver
from hockey.helpers.pretty_print import err, ok

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def ensure_players(cursor, game: Game) -> dict[int, int]:
    """Insert any roster players not yet in the player table.

    Returns sl_id → db_id map for all players in the roster.
    """
    for p in game.roster.players.values():
        cursor.execute(
            "INSERT IGNORE INTO player (sl_id, first_name, last_name) VALUES (%s, %s, %s)",
            (p.player_id, p.first_name, p.last_name),
        )
    return database.create_map('player', cursor, values=list(game.roster.players.keys()))


def ingest_affiliations(
    cursor,
    game: Game,
    player_map: dict[int, int],
    team_map: dict[int, int],
    game_db_id: int,
) -> None:
    """Insert one affiliation row per roster player (INSERT IGNORE)."""
    for p in game.roster.players.values():
        player_db_id = player_map.get(p.player_id)
        team_db_id = team_map.get(p.team_id)
        if player_db_id is None or team_db_id is None:
            err(f"Skipping affiliation for player {p.player_id}: missing player_id or team_id mapping")
            continue
        cursor.execute(
            "INSERT IGNORE INTO affiliation (player_id, team_id, game_id, jersey_number, position) "
            "VALUES (%s, %s, %s, %s, %s)",
            (player_db_id, team_db_id, game_db_id, None, p.position),
        )


def ingest_shifts(
    cursor,
    game: Game,
    player_map: dict[int, int],
    game_db_id: int,
) -> None:
    """Insert TOI intervals into shift (INSERT IGNORE)."""
    for toi in game.toi:
        player_db_id = player_map.get(toi.player_id)
        if player_db_id is None:
            err(f"Skipping shift for player {toi.player_id}: not in player_map")
            continue
        cursor.execute(
            "INSERT IGNORE INTO shift (player_id, game_id, in_time, out_time) VALUES (%s, %s, %s, %s)",
            (player_db_id, game_db_id, toi.start_t, toi.end_t),
        )


def _ingest_events_df(
    game: Game,
    player_map: dict[int, int],
    team_map_by_name: dict[str, int],
    game_db_id: int,
    event_columns: list[str],
) -> None:
    """Bulk-insert events via DataFrame → SQLAlchemy."""
    df = game.events_supplier_df().copy()
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)

    list_player_cols = [
        'team_forwards_on_ice_refs',
        'opposing_team_forwards_on_ice_refs',
        'team_defencemen_on_ice_refs',
        'opposing_team_defencemen_on_ice_refs',
    ]
    single_value_cols = [
        'team_goalie_on_ice_ref',
        'opposing_team_goalie_on_ice_ref',
        'player_reference_id',
    ]

    for col in list_player_cols:
        df[col] = df[col].fillna('').apply(
            lambda x: ', '.join(str(player_map.get(int(k))) for k in x if len(k) > 0) if x else ''
        )
    for col in single_value_cols:
        df[col] = df[col].fillna('').apply(
            lambda x: str(player_map.get(int(x))) if x else None
        )

    df['flags'] = df['flags'].fillna('').apply(lambda x: ', '.join(x) if x else '')
    df['team'] = df['team'].fillna('').apply(lambda x: team_map_by_name.get(x) if x else None)
    df['team_in_possession'] = df['team_in_possession'].fillna('').apply(
        lambda x: team_map_by_name.get(x) if x else None
    )
    df.insert(0, 'game_id', game_db_id)
    df.drop([c for c in df.columns if c not in event_columns], axis='columns', inplace=True)

    engine = database.sqlalchemy_engine_azure()
    try:
        df.to_sql('event', engine, if_exists='append', index=False)
        ok(f"Ingested {len(df)} events for game {game.game_id}")
    except Exception as e:
        err(f"Failed to ingest events for game {game.game_id}: {e}")


def ingest_events(game: Game) -> None:
    """Ingest a single game: players → affiliations → shifts → events."""
    db = database.open_database_azure()
    cursor = db.cursor()

    # Step 1: ensure all roster players exist; get complete player_map
    player_map = ensure_players(cursor, game)
    db.commit()

    # Build shared maps
    team_map_by_sl_id = database.create_map('team', cursor)
    game_map = database.create_map('game', cursor, [game.info.game_id])
    game_db_id = game_map.get(game.info.game_id)
    if game_db_id is None:
        cursor.close()
        raise ValueError(f"Game {game.info.game_id} not found in DB — run ingest_game first.")

    event_columns = database.get_table_columns('event', cursor)

    # Step 2: affiliations
    ingest_affiliations(cursor, game, player_map, team_map_by_sl_id, game_db_id)

    # Step 3: shifts
    ingest_shifts(cursor, game, player_map, game_db_id)

    db.commit()
    cursor.close()

    # Step 4: events (bulk insert via SQLAlchemy)
    resolver = TeamResolver.from_game_info(game.info)
    team_map_by_name = {
        resolver.home_display: team_map_by_sl_id.get(resolver.home_id),
        resolver.away_display: team_map_by_sl_id.get(resolver.away_id),
    }
    _ingest_events_df(game, player_map, team_map_by_name, game_db_id, event_columns)


if __name__ == "__main__":
    from hockey.catalog import DataCatalog

    LEAGUE_ID = 213
    SEASON = "20232024"

    catalog = DataCatalog(settings.data_root_dir)
    for game_id in tqdm(catalog.scheduled_game_ids(LEAGUE_ID, SEASON), desc="Ingesting games"):
        try:
            game = build_game(catalog.raw_game(game_id))
            ingest_events(game)
        except Exception as e:
            err(f"Skipping game {game_id}: {e}")
