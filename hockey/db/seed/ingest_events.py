"""Ingest one game into the v2 schema (hockey/db/schema/schema_v2.sql).

Differences from the v1 ingest, all following from the schema rewrite:

* ONE event table. There is no compiled/non-compiled split any more, because
  build_game produces the merged vocabulary by default.
* Rows are built from typed ``Event`` objects, not from
  ``events_supplier_df()``. The supplier payload spells things two different
  ways depending on the file; the Event does not.
* ``sl_event_id`` is written verbatim as a string. v1 forced it through
  ``int()``, which nulled every derived event's id.
* ``event.id`` is AUTO_INCREMENT, so no local id block has to be reserved.
  ``sl_base_event_id`` stays a supplier string and is resolved at query time,
  not at ingest.
* Flags go to ``event_flag``; they are no longer joined into a varchar.
* The on-ice refs are NOT written at all -- they are derivable from ``shift``.
"""
from __future__ import annotations

from pathlib import Path

from tqdm import tqdm

from hockey.catalog import DataCatalog
from hockey.db import database
from hockey.config.settings import Settings
from hockey.model.events import Event
from hockey.model.game import Game
from hockey.normalize.build_game import build_game
from hockey.helpers.pretty_print import err, ok

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

EVENT_TABLE = "event"

# Column order used by the bulk insert. Kept explicit so a schema change is a
# visible edit here rather than a silent mismatch.
EVENT_COLUMNS = (
    'game_id', 'sl_event_id', 'sl_base_event_id',
    'game_time', 'period', 'period_time',
    'name', 'type', 'outcome', 'shorthand',
    'team_id', 'player_id', 'team_in_possession',
    'zone', 'play_zone', 'play_section', 'x_adj_coord', 'y_adj_coord',
    'current_possession', 'current_play_in_possession',
    'is_possession_event', 'is_last_play_of_possession',
    'is_possession_breaking', 'is_defensive_event',
    'team_skaters_on_ice', 'opposing_team_skaters_on_ice',
    'manpower_situation', 'score_differential',
    'expected_goals_all_shots', 'expected_goals_all_shots_grade',
    'expected_goals_on_net', 'expected_goals_on_net_grade',
)

_ZONES = {'dz', 'nz', 'oz'}
_MANPOWER = {'evenStrength', 'powerPlay', 'shortHanded'}


def _clean(x):
    """None for the supplier's several spellings of 'absent'."""
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        return None if s in ('', 'none', 'None', 'NONE') else s
    if isinstance(x, float) and x != x:       # NaN
        return None
    return x


def _literal(x):
    """Like _clean, but keeps the supplier's literal "none".

    For `type` that string is a real category, not an absence marker -- every
    dumpinagainst and every carry has type "none", and the metric layer sees
    it as a value. Mapping it to NULL would make Event.type "" from the
    database and "none" from the files.
    """
    if x is None:
        return None
    if isinstance(x, str):
        return x.strip() or None
    if isinstance(x, float) and x != x:
        return None
    return x


def _enum(x, allowed: set[str]):
    """Guard an ENUM column: an unexpected value becomes NULL, not an error."""
    value = _clean(x)
    return value if value in allowed else None


def _bool(x):
    value = _clean(x)
    return None if value is None else bool(value)


def event_row(event: Event, game_db_id: int,
              player_map: dict[int, int], team_map: dict[int, int]) -> tuple:
    """One Event -> a tuple matching EVENT_COLUMNS."""
    raw = event.raw

    def team(sl_id):
        return team_map.get(sl_id) if sl_id else None

    return (
        game_db_id,
        # verbatim: derived events carry "<child>-<base>"
        str(_clean(raw.get('event_id')) or ''),
        _clean(raw.get('base_event_id')),
        float(event.t),
        _clean(raw.get('period')),
        _clean(raw.get('period_time')),
        event.name,
        _literal(event.type),
        _enum(event.outcome, {'successful', 'failed', 'undetermined'}),
        _clean(raw.get('shorthand')),
        team(event.team_id),
        player_map.get(event.player_id) if event.player_id else None,
        team(event.team_id_in_possession),
        _enum(event.zone, _ZONES),
        _enum(raw.get('play_zone'), _ZONES),
        _clean(event.play_section),
        _clean(raw.get('x_adj_coord')),
        _clean(raw.get('y_adj_coord')),
        event.current_possession,
        event.current_play_in_possession,
        _bool(raw.get('is_possession_event')),
        _bool(raw.get('is_last_play_of_possession')),
        _bool(raw.get('is_possession_breaking')),
        _bool(raw.get('is_defensive_event')),
        event.team_skaters_on_ice,
        event.opposing_team_skaters_on_ice,
        # compiled spells this "manpowersituation"; the linked value wins
        _enum(raw.get('manpower_situation') or raw.get('manpowersituation'), _MANPOWER),
        _clean(raw.get('score_differential')),
        _clean(event.expected_goals_all_shots),
        _clean(event.grade),
        _clean(event.expected_goals_on_net),
        _clean(event.expected_goals_on_net_grade),
    )


def ensure_players(cursor, game: Game) -> dict[int, int]:
    """Insert any roster players not yet in `player`; return sl_id -> db_id."""
    for p in game.roster.players.values():
        cursor.execute(
            "INSERT IGNORE INTO player (sl_id, first_name, last_name) VALUES (%s, %s, %s)",
            (p.player_id, p.first_name, p.last_name),
        )
    return database.create_map('player', cursor, values=list(game.roster.players.keys()))


def ensure_flags(cursor, games_flags: set[str]) -> dict[str, int]:
    """Insert any unseen flag names; return name -> flag_id."""
    for name in sorted(games_flags):
        cursor.execute("INSERT IGNORE INTO flag (name) VALUES (%s)", (name,))
    if not games_flags:
        return {}
    placeholders = ', '.join(['%s'] * len(games_flags))
    cursor.execute(f"SELECT name, id FROM flag WHERE name IN ({placeholders})",
                   tuple(sorted(games_flags)))
    return {name: fid for name, fid in cursor.fetchall()}


def ingest_affiliations(cursor, game: Game, player_map, team_map, game_db_id) -> None:
    for p in game.roster.players.values():
        player_db_id = player_map.get(p.player_id)
        team_db_id = team_map.get(p.team_id)
        if player_db_id is None or team_db_id is None:
            err(f"Skipping affiliation for player {p.player_id}: missing mapping")
            continue
        cursor.execute(
            "INSERT IGNORE INTO affiliation "
            "(player_id, team_id, game_id, jersey_number, position) "
            "VALUES (%s, %s, %s, %s, %s)",
            (player_db_id, team_db_id, game_db_id, None, p.position),
        )


def ingest_shifts(cursor, game: Game, player_map, game_db_id) -> None:
    """TOI intervals into `shift` -- the only record of who was on the ice.

    ``period`` is left NULL: Game.toi comes from playerTOI.json, which carries
    absolute game times but no period. shifts.json has it if it is ever wanted.
    """
    # The game can already have shifts without having events -- ingest_shifts.py
    # writes them on its own -- so the ones already stored are skipped here
    # rather than inserted a second time.
    existing = database.existing_shift_keys(game_db_id, cursor)
    rows = []
    duplicates = 0
    for toi in game.toi:
        player_db_id = player_map.get(toi.player_id)
        if player_db_id is None:
            err(f"Skipping shift for player {toi.player_id}: not in player_map")
            continue
        if database.shift_key(player_db_id, toi.start_t, toi.end_t) in existing:
            duplicates += 1
            continue
        rows.append((game_db_id, player_db_id, None, toi.start_t, toi.end_t))
    if duplicates:
        ok(f"{duplicates} shifts already in `shift`, not written again")
    if rows:
        cursor.executemany(
            "INSERT INTO shift (game_id, player_id, period, in_time, out_time) "
            "VALUES (%s, %s, %s, %s, %s)", rows)


def ingest_event_rows(cursor, game: Game, player_map, team_map, game_db_id) -> int:
    """Bulk-insert events, then their flags. Returns the number of events."""
    rows = [event_row(e, game_db_id, player_map, team_map) for e in game.events]
    if not rows:
        return 0
    placeholders = ', '.join(['%s'] * len(EVENT_COLUMNS))
    columns = ', '.join(f"`{c}`" for c in EVENT_COLUMNS)
    cursor.executemany(
        f"INSERT INTO {EVENT_TABLE} ({columns}) VALUES ({placeholders})", rows)

    # Flags need the generated ids, so read them back by supplier id.
    flag_names = {f for e in game.events for f in e.flags}
    flag_map = ensure_flags(cursor, flag_names)
    cursor.execute(
        f"SELECT sl_event_id, id FROM {EVENT_TABLE} WHERE game_id = %s", (game_db_id,))
    id_by_sl = {sl: db_id for sl, db_id in cursor.fetchall()}

    flag_rows = []
    for e in game.events:
        if not e.flags:
            continue
        event_db_id = id_by_sl.get(str(e.get_raw('event_id')))
        if event_db_id is None:
            continue
        for f in e.flags:
            flag_id = flag_map.get(f)
            if flag_id is not None:
                flag_rows.append((event_db_id, flag_id))
    if flag_rows:
        cursor.executemany(
            "INSERT IGNORE INTO event_flag (event_id, flag_id) VALUES (%s, %s)",
            flag_rows)
    return len(rows)


def ingest_events(game: Game, conn=None) -> None:
    """Ingest one game: players -> affiliations -> shifts -> events -> flags.

    The whole game is one transaction: a half-ingested game is worse than an
    absent one, since categorize_game_ids treats any events as 'done'.
    """
    db = conn or database.open_database_azure()
    owns = conn is None
    cursor = db.cursor()
    try:
        player_map = ensure_players(cursor, game)
        team_map = database.create_map('team', cursor)
        game_map = database.create_map('game', cursor, [game.info.game_id])
        game_db_id = game_map.get(game.info.game_id)
        if game_db_id is None:
            raise ValueError(
                f"Game {game.info.game_id} not in DB -- run ingest_game first.")

        cursor.execute(
            f"SELECT COUNT(*) FROM {EVENT_TABLE} WHERE game_id = %s", (game_db_id,))
        if cursor.fetchone()[0]:
            ok(f"Game {game.info.game_id} already ingested, skipping.")
            return

        ingest_affiliations(cursor, game, player_map, team_map, game_db_id)
        ingest_shifts(cursor, game, player_map, game_db_id)
        n = ingest_event_rows(cursor, game, player_map, team_map, game_db_id)
        db.commit()
        ok(f"Ingested {n} events for game {game.info.game_id}")
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        if owns:
            db.close()


def categorize_game_ids(game_ids: list[int]) -> tuple[list[int], int, int]:
    """Split game_ids into (to_ingest, already_ingested, not_yet_played)."""
    placeholders = ', '.join(['%s'] * len(game_ids))
    db = database.open_database_azure()
    cursor = db.cursor()
    cursor.execute(
        f"""
        SELECT g.sl_id, g.event_status, COUNT(e.id) AS event_count
        FROM game g
        LEFT JOIN {EVENT_TABLE} e ON e.game_id = g.id
        WHERE g.sl_id IN ({placeholders})
        GROUP BY g.sl_id, g.event_status
        """,
        game_ids,
    )
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    to_ingest = [r[0] for r in rows if r[1] == 'over' and r[2] == 0]
    return (to_ingest,
            sum(1 for r in rows if r[1] == 'over' and r[2] > 0),
            sum(1 for r in rows if r[1] != 'over'))


def ingest_one_game(game_id: int) -> None:
    catalog = DataCatalog(settings.data_root_dir)
    ingest_events(build_game(catalog.raw_game(game_id)))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=int, help="ingest this one game and stop")
    parser.add_argument("--league", type=int, default=13)
    parser.add_argument("--season", default="20242025")
    args = parser.parse_args()

    if args.game is not None:
        ingest_one_game(args.game)
        raise SystemExit

    catalog = DataCatalog(settings.data_root_dir)
    all_ids = list(catalog.scheduled_game_ids(args.league, args.season))
    to_ingest, already, not_played = categorize_game_ids(all_ids)
    loadable = [g for g in to_ingest if catalog.game_fileset(g).is_loadable]
    done = 0
    for game_id in tqdm(loadable, desc=f"Ingesting into {EVENT_TABLE}"):
        try:
            ingest_events(build_game(catalog.raw_game(game_id)))
            done += 1
        except Exception as e:
            err(f"Skipping game {game_id}: {e}")
    ok(f"{done} games ingested, {already} already, {not_played} not yet played, "
       f"{len(to_ingest) - len(loadable)} missing files.")
