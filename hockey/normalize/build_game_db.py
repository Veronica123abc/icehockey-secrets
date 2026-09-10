from __future__ import annotations

from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.model.roster import Player, Roster
from hockey.model.toi import ToIInterval
from hockey.normalize.event_rows import IdMaps, event_from_row, maybe_int
from hockey.normalize.on_ice_from_shifts import (on_ice_at_times,
                                                 own_team_for_event,
                                                 split_by_team_and_position)

# Back-compat alias; the v1 helper of this name lived here.
_maybe_int = maybe_int


def build_game_from_db(game_sl_id: int, conn) -> Game:
    """Reconstruct a Game by querying the v2 schema (no JSON files required).

    There is no ``compiled`` switch any more: the v2 `event` table holds one
    merged vocabulary, the same stream build_game produces from the two
    playsequence files.

    IDs on the returned model objects use SportLogIQ sl_ids (not DB PKs),
    matching build_game() from JSON.

    ``e.raw`` mirrors the supplier payload rather than the row: the two id
    columns are re-keyed to ``event_id``/``base_event_id``, flags arrive as a
    list, and the on-ice refs -- which the schema does not store -- are
    reconstructed from `shift` joined to `affiliation` for position. An Event
    from here should be indistinguishable from one built off the files.
    """
    cursor = conn.cursor()
    try:
        # --- 1. Game metadata + team info --------------------------------
        cursor.execute(
            """
            SELECT g.id, g.sl_id,
                   ht.sl_id, ht.location, ht.name,
                   at.sl_id, at.location, at.name,
                   g.stage, g.scheduled_time, g.home_team_goals, g.away_team_goals
            FROM game g
            JOIN team ht ON ht.id = g.home_team_id
            JOIN team at ON at.id = g.away_team_id
            WHERE g.sl_id = %s
            """,
            (game_sl_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Game {game_sl_id} not found in database")

        (game_db_id, game_id, home_sl, home_loc, home_name,
         away_sl, away_loc, away_name,
         stage, scheduled_time, home_goals, away_goals) = row

        info = GameInfo(
            game_id=game_id,
            home_team=TeamInfo(id=home_sl, location=home_loc or "", name=home_name or ""),
            away_team=TeamInfo(id=away_sl, location=away_loc or "", name=away_name or ""),
            date=scheduled_time.date().isoformat() if scheduled_time else None,
            stage=stage,
            home_final_score=home_goals,
            away_final_score=away_goals,
        )

        # --- 2. Reverse maps: DB pk -> sl_id -----------------------------
        cursor.execute(
            """
            SELECT p.id, p.sl_id
            FROM player p
            JOIN affiliation a ON a.player_id = p.id
            WHERE a.game_id = %s
            """,
            (game_db_id,),
        )
        player_db_to_sl: dict[int, int] = dict(cursor.fetchall())

        cursor.execute(
            """
            SELECT t.id, t.sl_id
            FROM team t
            JOIN game g ON (t.id = g.home_team_id OR t.id = g.away_team_id)
            WHERE g.id = %s
            """,
            (game_db_id,),
        )
        team_db_to_sl: dict[int, int] = dict(cursor.fetchall())
        ids = IdMaps(player_db_to_sl=player_db_to_sl, team_db_to_sl=team_db_to_sl)

        # --- 3. Roster ---------------------------------------------------
        cursor.execute(
            """
            SELECT p.sl_id, t.sl_id, p.first_name, p.last_name, a.position
            FROM affiliation a
            JOIN player p ON p.id = a.player_id
            JOIN team t ON t.id = a.team_id
            WHERE a.game_id = %s
            """,
            (game_db_id,),
        )
        players = {
            p_sl: Player(player_id=p_sl, team_id=t_sl,
                         first_name=fn, last_name=ln, position=pos)
            for p_sl, t_sl, fn, ln, pos in cursor.fetchall()
        }
        roster = Roster(game_id=game_id, players=players)

        # --- 4. Shifts ----------------------------------------------------
        # Team comes via affiliation: shift does not carry it, because the
        # player's team for a game is affiliation's business, not a shift's.
        cursor.execute(
            """
            SELECT p.sl_id, t.sl_id, s.in_time, s.out_time
            FROM shift s
            JOIN player p ON p.id = s.player_id
            LEFT JOIN affiliation a ON a.player_id = s.player_id AND a.game_id = s.game_id
            LEFT JOIN team t ON t.id = a.team_id
            WHERE s.game_id = %s
            """,
            (game_db_id,),
        )
        toi = [
            ToIInterval(
                game_id=game_id,
                team_id=t_sl,
                player_id=p_sl,
                start_t=float(in_t),
                end_t=float(out_t) if out_t is not None else None,
            )
            for p_sl, t_sl, in_t, out_t in cursor.fetchall()
        ]

        # --- 5. Events, flags, on-ice -------------------------------------
        dict_cursor = conn.cursor(dictionary=True)
        try:
            dict_cursor.execute(
                "SELECT * FROM event WHERE game_id = %s ORDER BY game_time",
                (game_db_id,),
            )
            rows = dict_cursor.fetchall()
        finally:
            dict_cursor.close()

        cursor.execute(
            """
            SELECT ef.event_id, f.name
            FROM event_flag ef
            JOIN flag f ON f.id = ef.flag_id
            JOIN event e ON e.id = ef.event_id
            WHERE e.game_id = %s
            """,
            (game_db_id,),
        )
        flags_by_event: dict[int, list[str]] = {}
        for event_db_id, flag_name in cursor.fetchall():
            flags_by_event.setdefault(event_db_id, []).append(flag_name)

        on_ice_sets = on_ice_at_times(toi, [float(r['game_time']) for r in rows])
        events = []
        for r, on_ice in zip(rows, on_ice_sets):
            event_team = team_db_to_sl.get(r.get('team_id'))
            credited = players.get(player_db_to_sl.get(r.get('player_id')))
            own_team = own_team_for_event(
                name=r.get('name') or "",
                outcome=r.get('outcome'),
                event_team_id=event_team,
                credited_position=credited.position if credited else None,
                home_team_id=info.home_team.id,
                away_team_id=info.away_team.id,
            )
            events.append(event_from_row(
                r, game_id=game_id, ids=ids,
                flags=flags_by_event.get(r['id'], []),
                on_ice=split_by_team_and_position(on_ice, roster, own_team),
            ))

        return Game(info=info, events=events, toi=toi, roster=roster)

    finally:
        cursor.close()
