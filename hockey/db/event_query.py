"""Cross-game event queries against the v2 schema.

The metric layer in ``hockey/derive`` is a pile of predicates over ``Event``
-- ``is_slot(e)``, ``pass_components(e)``, ``player_differential(e)``. None of
them care where the Event came from. So a season-wide metric does not need
whole games: it needs the right *subset* of events, as Events.

That is the split this module serves. Coarse filters that the database can
answer with an index go in the query (league, season, game, player, team,
event name); everything finer stays in Python::

    events = query_events(conn, league_sl_id=17, season="20252026",
                          player_sl_id=9861, names=["shot"])
    slot_shots = [e for e in events if is_slot(e)]

Loading one game is ~0.3s, so a 410-game season is ~2 minutes; the same
question asked as one indexed query is milliseconds.

ON-ICE IS OFF BY DEFAULT. The v2 schema derives on-ice from `shift`, which
means reconstructing it needs every shift of every game touched -- worth it
for one game, wasteful for a narrow season query. With ``with_on_ice=False``
the returned Events have empty on-ice refs, which ``Event.players_on_ice``
documents as "unknown", not "nobody". Pass ``with_on_ice=True`` when a metric
actually reads them.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from hockey.model.events import Event
from hockey.model.roster import Player, Roster
from hockey.model.toi import ToIInterval
from hockey.normalize.event_rows import IdMaps, event_from_row
from hockey.config.settings import Settings

# event_flag lookups are chunked so a season-wide result does not build a
# single IN clause with a million placeholders.
_CHUNK = 5000
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def _placeholders(values: Sequence) -> str:
    return ', '.join(['%s'] * len(values))


def _sl_to_db(cursor, table: str, sl_ids: Iterable[int]) -> dict[int, int]:
    sl_ids = list(sl_ids)
    if not sl_ids:
        return {}
    cursor.execute(
        f"SELECT sl_id, id FROM `{table}` WHERE sl_id IN ({_placeholders(sl_ids)})",
        tuple(sl_ids))
    return dict(cursor.fetchall())


def _flags_for(cursor, event_db_ids: Sequence[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for start in range(0, len(event_db_ids), _CHUNK):
        chunk = event_db_ids[start:start + _CHUNK]
        cursor.execute(
            f"""SELECT ef.event_id, f.name
                FROM event_flag ef JOIN flag f ON f.id = ef.flag_id
                WHERE ef.event_id IN ({_placeholders(chunk)})""",
            tuple(chunk))
        for event_id, flag in cursor.fetchall():
            out.setdefault(event_id, []).append(flag)
    return out


def _on_ice_for(conn, game_db_ids: Sequence[int], rows: Sequence[dict],
                ids: IdMaps) -> dict[int, dict]:
    """Reconstruct on-ice refs for the returned rows, per game."""
    from hockey.normalize.on_ice_from_shifts import (on_ice_at_times,
                                                     own_team_for_event,
                                                     split_by_team_and_position)
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""SELECT s.game_id, p.sl_id, t.sl_id, s.in_time, s.out_time
                FROM shift s
                JOIN player p ON p.id = s.player_id
                LEFT JOIN affiliation a ON a.player_id = s.player_id AND a.game_id = s.game_id
                LEFT JOIN team t ON t.id = a.team_id
                WHERE s.game_id IN ({_placeholders(game_db_ids)})""",
            tuple(game_db_ids))
        toi_by_game: dict[int, list[ToIInterval]] = {}
        for game_db_id, p_sl, t_sl, in_t, out_t in cursor.fetchall():
            toi_by_game.setdefault(game_db_id, []).append(
                ToIInterval(game_id=game_db_id, team_id=t_sl, player_id=p_sl,
                            start_t=float(in_t),
                            end_t=float(out_t) if out_t is not None else None))

        cursor.execute(
            f"""SELECT a.game_id, p.sl_id, t.sl_id, p.first_name, p.last_name, a.position
                FROM affiliation a
                JOIN player p ON p.id = a.player_id
                JOIN team t ON t.id = a.team_id
                WHERE a.game_id IN ({_placeholders(game_db_ids)})""",
            tuple(game_db_ids))
        roster_by_game: dict[int, dict] = {}
        for game_db_id, p_sl, t_sl, fn, ln, pos in cursor.fetchall():
            roster_by_game.setdefault(game_db_id, {})[p_sl] = Player(
                player_id=p_sl, team_id=t_sl, first_name=fn, last_name=ln, position=pos)

        cursor.execute(
            f"""SELECT id, home_team_id, away_team_id FROM game
                WHERE id IN ({_placeholders(game_db_ids)})""",
            tuple(game_db_ids))
        teams_by_game = {g: (h, a) for g, h, a in cursor.fetchall()}
    finally:
        cursor.close()

    by_game: dict[int, list[dict]] = {}
    for row in rows:
        by_game.setdefault(row['game_id'], []).append(row)

    out: dict[int, dict] = {}
    for game_db_id, game_rows in by_game.items():
        toi = toi_by_game.get(game_db_id, [])
        roster = Roster(game_id=game_db_id,
                        players=roster_by_game.get(game_db_id, {}))
        home_db, away_db = teams_by_game.get(game_db_id, (None, None))
        home_sl, away_sl = ids.team(home_db), ids.team(away_db)
        sets = on_ice_at_times(toi, [float(r['game_time']) for r in game_rows])
        for row, on_ice in zip(game_rows, sets):
            credited = roster.players.get(ids.player(row.get('player_id')))
            own = own_team_for_event(
                name=row.get('name') or "",
                outcome=row.get('outcome'),
                event_team_id=ids.team(row.get('team_id')),
                credited_position=credited.position if credited else None,
                home_team_id=home_sl, away_team_id=away_sl)
            out[row['id']] = split_by_team_and_position(on_ice, roster, own)
    return out


def query_events(conn, *,
                 league_sl_id: int | None = None,
                 season: str | None = None,
                 game_sl_ids: Iterable[int] | None = None,
                 player_sl_id: int | None = None,
                 team_sl_id: int | None = None,
                 on_ice_player_sl_id: int | None = None,
                 names: Iterable[str] | None = None,
                 outcomes: Iterable[str] | None = None,
                 zones: Iterable[str] | None = None,
                 with_on_ice: bool = False,
                 limit: int | None = None) -> list[Event]:
    """Events matching the coarse filters, as :class:`Event` objects.

    All ids are SportLogIQ ids, matching the rest of the model layer.

    ``player_sl_id`` is the event's own player -- who took the shot.
    ``on_ice_player_sl_id`` is different: every event that happened while that
    player was on the ice, via an interval join against `shift`. A player has
    ~25 shifts a game, so the join narrows hard before the range test.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        plain = conn.cursor()
        try:
            player_db = (_sl_to_db(plain, 'player', [player_sl_id]).get(player_sl_id)
                         if player_sl_id else None)
            on_ice_db = (_sl_to_db(plain, 'player', [on_ice_player_sl_id]).get(on_ice_player_sl_id)
                         if on_ice_player_sl_id else None)
            team_db = (_sl_to_db(plain, 'team', [team_sl_id]).get(team_sl_id)
                       if team_sl_id else None)
            if player_sl_id and player_db is None:
                return []
            if on_ice_player_sl_id and on_ice_db is None:
                return []
            if team_sl_id and team_db is None:
                return []
        finally:
            plain.close()

        where: list[str] = []
        params: list = []
        joins = ["JOIN game g ON g.id = e.game_id"]

        if on_ice_db is not None:
            joins.append(
                "JOIN shift s ON s.game_id = e.game_id AND s.player_id = %s "
                "AND e.game_time >= s.in_time "
                "AND (s.out_time IS NULL OR e.game_time < s.out_time)")
            params.append(on_ice_db)
        if league_sl_id is not None:
            where.append("g.league_id = (SELECT id FROM league WHERE sl_id = %s)")
            params.append(league_sl_id)
        if season is not None:
            where.append("g.season = %s")
            params.append(season)
        if game_sl_ids:
            game_sl_ids = list(game_sl_ids)
            where.append(f"g.sl_id IN ({_placeholders(game_sl_ids)})")
            params.extend(game_sl_ids)
        if player_db is not None:
            where.append("e.player_id = %s")
            params.append(player_db)
        if team_db is not None:
            where.append("e.team_id = %s")
            params.append(team_db)
        if names:
            names = list(names)
            where.append(f"e.name IN ({_placeholders(names)})")
            params.extend(names)
        if outcomes:
            outcomes = list(outcomes)
            where.append(f"e.outcome IN ({_placeholders(outcomes)})")
            params.extend(outcomes)
        if zones:
            zones = list(zones)
            where.append(f"e.zone IN ({_placeholders(zones)})")
            params.extend(zones)

        sql = (f"SELECT e.*, g.sl_id AS game_sl_id FROM event e {' '.join(joins)}"
               + (f" WHERE {' AND '.join(where)}" if where else "")
               + " ORDER BY e.game_id, e.game_time")
        if limit:
            sql += " LIMIT %s"
            params.append(int(limit))
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        if not rows:
            return []

        plain = conn.cursor()
        try:
            plain.execute("SELECT id, sl_id FROM player")
            player_db_to_sl = dict(plain.fetchall())
            plain.execute("SELECT id, sl_id FROM team")
            team_db_to_sl = dict(plain.fetchall())
            ids = IdMaps(player_db_to_sl=player_db_to_sl, team_db_to_sl=team_db_to_sl)
            flags = _flags_for(plain, [r['id'] for r in rows])
        finally:
            plain.close()

        on_ice = {}
        if with_on_ice:
            on_ice = _on_ice_for(conn, sorted({r['game_id'] for r in rows}), rows, ids)

        return [
            event_from_row(r, game_id=r['game_sl_id'], ids=ids,
                           flags=flags.get(r['id'], []),
                           on_ice=on_ice.get(r['id']))
            for r in rows
        ]
    finally:
        cursor.close()




if __name__ == "__main__":
    # Hardcoded so this runs from the IDE's run/debug button with no arguments.
    # Edit these, set a breakpoint anywhere below, and step in.
    #
    # The connection honours the DATABASE_*_AZURE variables in .env, so point
    # those at localhost to query a local database instead of Azure.
    LEAGUE_SL_ID = 17
    SEASON = "20252026"
    PLAYER_SL_ID = 24417        # None for every player
    TEAM_SL_ID = None
    ON_ICE_PLAYER_SL_ID = 24417   # events while this player was on the ice
    NAMES = ["shot"]            # None for every event type
    OUTCOMES = None             # e.g. ["successful"]
    ZONES = None                # e.g. ["oz"]
    WITH_ON_ICE = False
    LIMIT = None

    import time
    from collections import Counter

    from hockey.db import database

    conn = database.open_database_azure()
    try:
        started = time.perf_counter()
        events = query_events(
            conn,
            league_sl_id=LEAGUE_SL_ID,
            season=SEASON,
            player_sl_id=PLAYER_SL_ID,
            team_sl_id=TEAM_SL_ID,
            on_ice_player_sl_id=ON_ICE_PLAYER_SL_ID,
            names=NAMES,
            outcomes=OUTCOMES,
            zones=ZONES,
            with_on_ice=WITH_ON_ICE,
            limit=LIMIT,
        )
        elapsed = time.perf_counter() - started

        print(f"{len(events):,} events in {elapsed*1000:.0f} ms "
              f"across {len({e.game_id for e in events})} games")
        print(f"  names    : {dict(Counter(e.name for e in events).most_common(6))}")
        print(f"  outcomes : {dict(Counter(e.outcome for e in events))}")
        print(f"  types    : {dict(Counter(e.type for e in events).most_common(6))}")
        print(f"  zones    : {dict(Counter(e.zone for e in events))}")

        print("\nfirst few:")
        for e in events[:5]:
            print(f"   game {e.game_id}  t={e.t:8.2f}  {e.name:12s} {e.type or '-':16s} "
                  f"{e.outcome or '-':12s} player={e.player_id} flags={e.flags}")

        # The point of returning Events: the derive predicates work unchanged.
        from hockey.derive.shooting.metrics import is_slot, is_one_timer, is_on_net
        shots = [e for e in events if e.name == "shot"]
        if shots:
            print(f"\nof {len(shots):,} shots: "
                  f"slot {sum(1 for e in shots if is_slot(e))}, "
                  f"1-timers {sum(1 for e in shots if is_one_timer(e))}, "
                  f"on net {sum(1 for e in shots if is_on_net(e))}")
    finally:
        conn.close()
