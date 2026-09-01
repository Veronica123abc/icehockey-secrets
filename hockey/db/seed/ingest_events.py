from __future__ import annotations

import numpy as np
from pathlib import Path
from tqdm import tqdm

from hockey.db import database
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.model.game import Game
from hockey.normalize.build_game import build_game
from hockey.normalize.team_resolution import TeamResolver
from hockey.helpers.pretty_print import err, ok

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

# The two event tables. `event` holds playsequence.json, `compiled_event` holds
# playsequence_compiled.json enriched with the fields only playsequence.json
# carries (see RawGame.LINKED_FIELDS). They are kept in parallel for now.
EVENT_TABLE = "event"
COMPILED_EVENT_TABLE = "compiled_event"

LIST_PLAYER_COLUMNS = (
    'team_forwards_on_ice_refs',
    'opposing_team_forwards_on_ice_refs',
    'team_defencemen_on_ice_refs',
    'opposing_team_defencemen_on_ice_refs',
)


def event_table(compiled: bool) -> str:
    return COMPILED_EVENT_TABLE if compiled else EVENT_TABLE


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


def _has_value(x) -> bool:
    """True for a real scalar; False for None and NaN."""
    return x is not None and x == x


def _ensure_columns(df, columns) -> None:
    """Add any column the events don't carry, so the mapping below is uniform.

    Compiled events that never linked back to playsequence.json have no
    on-ice or expected-goals keys at all, so the whole column can be absent.
    """
    for col in columns:
        if col not in df.columns:
            df[col] = np.nan


def _map_player_ref_lists(df, player_map: dict[int, int]) -> None:
    """Turn the on-ice sl_id lists into ', '-joined db ids."""
    for col in LIST_PLAYER_COLUMNS:
        df[col] = df[col].fillna('').apply(
            lambda x: ', '.join(str(player_map.get(int(k))) for k in x if len(str(k)) > 0) if x else ''
        )


def _write(df, table: str, game_id: int) -> None:
    engine = database.sqlalchemy_engine_azure()
    try:
        df.to_sql(table, engine, if_exists='append', index=False)
        ok(f"Ingested {len(df)} events into {table} for game {game_id}")
    except Exception as e:
        err(f"Failed to ingest events into {table} for game {game_id}: {e}")


def _ingest_events_df(
    game: Game,
    player_map: dict[int, int],
    team_map_by_name: dict[str, int],
    game_db_id: int,
    event_columns: list[str],
) -> None:
    """Bulk-insert playsequence.json events into `event` via DataFrame → SQLAlchemy."""
    df = game.events_supplier_df().copy()
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)

    single_value_cols = [
        'team_goalie_on_ice_ref',
        'opposing_team_goalie_on_ice_ref',
        'player_reference_id',
    ]

    _ensure_columns(df, LIST_PLAYER_COLUMNS)
    _map_player_ref_lists(df, player_map)
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

    _write(df, EVENT_TABLE, game.game_id)


def _ingest_compiled_events_df(
    game: Game,
    player_map: dict[int, int],
    team_map_by_sl_id: dict[int, int],
    game_db_id: int,
    event_columns: list[str],
    first_id: int,
) -> None:
    """Bulk-insert playsequence_compiled.json events into `compiled_event`.

    The compiled payload names things differently from playsequence.json:

    - the supplier's event ids are strings ("3676705759-211760296" for derived
      events), so they go to sl_event_id / sl_base_event_id, while `id` and
      `base_event_id` hold local ints. Those are assigned here, starting at
      `first_id`, because compiled_event.id is not AUTO_INCREMENT and
      base_event_id has to point at a row in this same batch (every
      base_event_id resolves within its own game).
    - teams come as numeric sl ids rather than display names, and the player is
      `player_id` rather than `player_reference_id`.

    The on-ice rosters, play_section and the expected-goals columns are not in
    the compiled file at all; normalize_playsequence folds them into the event
    payload from playsequence.json, so they arrive here as ordinary columns.
    """
    df = game.events_supplier_df().copy()
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)

    df = df.rename(columns={'event_id': 'sl_event_id', 'base_event_id': 'sl_base_event_id'})
    _ensure_columns(df, RawGame.LINKED_FIELDS)

    local_ids = list(range(first_id, first_id + len(df)))
    df.insert(0, 'id', local_ids)
    id_by_sl_id = dict(zip(df['sl_event_id'], local_ids))
    df['base_event_id'] = df['sl_base_event_id'].apply(
        lambda x: id_by_sl_id.get(x) if _has_value(x) else None
    )

    _map_player_ref_lists(df, player_map)
    df['player_id'] = df['player_id'].apply(
        lambda x: player_map.get(int(x)) if _has_value(x) else None
    )
    for col in ('team_id', 'team_in_possession'):
        df[col] = df[col].apply(
            lambda x: team_map_by_sl_id.get(int(x)) if _has_value(x) else None
        )

    df['flags'] = df['flags'].fillna('').apply(lambda x: ', '.join(x) if x else '')
    df['game_id'] = game_db_id
    df.drop([c for c in df.columns if c not in event_columns], axis='columns', inplace=True)

    _write(df, COMPILED_EVENT_TABLE, game.game_id)


def _next_compiled_event_id(cursor) -> int:
    """The id to start the next batch at; compiled_event.id is not AUTO_INCREMENT."""
    cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {COMPILED_EVENT_TABLE}")
    return int(cursor.fetchone()[0])


def categorize_game_ids(game_ids: list[int], *, compiled: bool = False) -> tuple[list[int], int, int]:
    """Categorize game_ids based on DB state.

    Returns:
        to_ingest:        game_ids with event_status='over' and no events stored yet
        already_ingested: count of games with event_status='over' that already have events
        not_yet_played:   count of games in DB with event_status != 'over'
    """
    table = event_table(compiled)
    placeholders = ', '.join(['%s'] * len(game_ids))
    db = database.open_database_azure()
    cursor = db.cursor()
    cursor.execute(
        f"""
        SELECT g.sl_id, g.event_status, COUNT(e.id) AS event_count
        FROM game g
        LEFT JOIN {table} e ON e.game_id = g.id
        WHERE g.sl_id IN ({placeholders})
        GROUP BY g.sl_id, g.event_status
        """,
        game_ids,
    )
    rows = cursor.fetchall()
    cursor.close()
    db.close()

    to_ingest = [row[0] for row in rows if row[1] == 'over' and row[2] == 0]
    already_ingested = sum(1 for row in rows if row[1] == 'over' and row[2] > 0)
    not_yet_played = sum(1 for row in rows if row[1] != 'over')
    return to_ingest, already_ingested, not_yet_played


def ingest_events(game: Game, *, compiled: bool = False) -> None:
    """Ingest a single game: players → affiliations → shifts → events.

    ``compiled=False`` ingests into `event` and expects a Game built from
    playsequence.json; ``compiled=True`` ingests into `compiled_event` and
    expects one built from playsequence_compiled.json.
    """
    table = event_table(compiled)
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

    event_columns = database.get_table_columns(table, cursor)

    # Step 2: affiliations
    ingest_affiliations(cursor, game, player_map, team_map_by_sl_id, game_db_id)

    # Step 3: shifts
    ingest_shifts(cursor, game, player_map, game_db_id)

    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE game_id = %s", (game_db_id,))
    events_exist = cursor.fetchone()[0] > 0
    first_id = _next_compiled_event_id(cursor) if compiled and not events_exist else 0

    db.commit()
    cursor.close()

    if events_exist:
        ok(f"Game {game.info.game_id} already has rows in {table}, skipping.")
        return

    # Step 4: events (bulk insert via SQLAlchemy)
    if compiled:
        _ingest_compiled_events_df(
            game, player_map, team_map_by_sl_id, game_db_id, event_columns, first_id
        )
        return

    resolver = TeamResolver.from_game_info(game.info)
    team_map_by_name = {
        resolver.home_display: team_map_by_sl_id.get(resolver.home_id),
        resolver.away_display: team_map_by_sl_id.get(resolver.away_id),
    }
    _ingest_events_df(game, player_map, team_map_by_name, game_db_id, event_columns)


if __name__ == "__main__":
    import argparse

    from hockey.catalog import DataCatalog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compiled",
        action="store_true",
        help="ingest playsequence_compiled.json into compiled_event "
             "(default: playsequence.json into event)",
    )
    parser.add_argument("--league", type=int, default=17, help="league id (default: 17)")
    parser.add_argument("--season", default="20252026", help="season (default: 20252026)")
    args = parser.parse_args()

    source = "playsequence_compiled" if args.compiled else "playsequence"

    catalog = DataCatalog(settings.data_root_dir)
    all_game_ids = list(catalog.scheduled_game_ids(args.league, args.season))
    game_ids_to_ingest, already_ingested, not_yet_played = categorize_game_ids(
        all_game_ids, compiled=args.compiled
    )
    loadable = [
        gid for gid in game_ids_to_ingest
        if (fs := catalog.game_fileset(gid)).is_loadable and source in fs.present
    ]
    missing_files = len(game_ids_to_ingest) - len(loadable)
    ingested_this_run = 0
    for game_id in tqdm(loadable, desc=f"Ingesting games into {event_table(args.compiled)}"):
        try:
            game = build_game(catalog.raw_game(game_id, playsequence_source=source))
            ingest_events(game, compiled=args.compiled)
            ingested_this_run += 1
        except Exception as e:
            err(f"Skipping game {game_id}: {e}")
    ok(
        f"Events for {ingested_this_run} games ingested, "
        f"{already_ingested} already ingested, "
        f"{not_yet_played} not yet played, "
        f"{missing_files} played but missing game files."
    )
