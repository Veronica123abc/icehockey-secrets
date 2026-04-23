from __future__ import annotations

from hockey.model.events import Event
from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.model.roster import Player, Roster
from hockey.model.toi import ToIInterval


def build_game_from_db(game_sl_id: int, conn) -> Game:
    """Reconstruct a Game by querying the database (no JSON files required).

    IDs on the returned model objects use SportLogIQ sl_ids (not DB PKs),
    matching the convention established by build_game() from JSON.

    e.raw is populated with the full event row (all columns), mirroring the
    JSON path where e.raw is the complete supplier payload. Note that FK
    columns (team_in_possession, team, player_reference_id, etc.) contain
    integer DB PKs in raw rather than sl_ids or display strings — use the
    structured Event fields (e.team_id, e.player_id, …) for identity lookups.
    """
    cursor = conn.cursor()
    try:
        # --- 1. Game metadata + team info --------------------------------
        cursor.execute(
            """
            SELECT g.id, g.sl_id,
                   ht.sl_id, ht.location, ht.name,
                   at.sl_id, at.location, at.name
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

        game_db_id, game_id, home_sl, home_loc, home_name, away_sl, away_loc, away_name = row

        info = GameInfo(
            game_id=game_id,
            home_team=TeamInfo(id=home_sl, location=home_loc or "", name=home_name or ""),
            away_team=TeamInfo(id=away_sl, location=away_loc or "", name=away_name or ""),
        )

        # --- 2. Reverse maps: DB pk → sl_id for players/teams in this game ---
        cursor.execute(
            """
            SELECT p.id, p.sl_id
            FROM player p
            JOIN affiliation a ON a.player_id = p.id
            WHERE a.game_id = %s
            """,
            (game_db_id,),
        )
        player_db_to_sl: dict[int, int] = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute(
            """
            SELECT t.id, t.sl_id
            FROM team t
            JOIN game g ON (t.id = g.home_team_id OR t.id = g.away_team_id)
            WHERE g.id = %s
            """,
            (game_db_id,),
        )
        team_db_to_sl: dict[int, int] = {r[0]: r[1] for r in cursor.fetchall()}

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
            p_sl: Player(player_id=p_sl, team_id=t_sl, first_name=fn, last_name=ln, position=pos)
            for p_sl, t_sl, fn, ln, pos in cursor.fetchall()
        }
        roster = Roster(game_id=game_id, players=players)

        # --- 4. TOI (shifts) ---------------------------------------------
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

        # --- 5. Events ---------------------------------------------------
        dict_cursor = conn.cursor(dictionary=True)
        try:
            dict_cursor.execute(
                "SELECT * FROM event WHERE game_id = %s ORDER BY game_time",
                (game_db_id,),
            )
            rows = dict_cursor.fetchall()
        finally:
            dict_cursor.close()

        def _parse_refs(s: str | None) -> list[int] | None:
            if not s:
                return None
            result = []
            for tok in s.split(","):
                tok = tok.strip()
                if tok and tok != "None":
                    try:
                        sl = player_db_to_sl.get(int(tok))
                        if sl is not None:
                            result.append(sl)
                    except ValueError:
                        pass
            return result or None

        events = [
            Event(
                game_id=game_id,
                t=float(row['game_time']),
                type=row.get('type') or "",
                name=row.get('name') or "",
                team_id_in_possession=team_db_to_sl.get(row['team_in_possession']) if row.get('team_in_possession') else None,
                team_id=team_db_to_sl.get(row['team']) if row.get('team') else None,
                player_id=player_db_to_sl.get(row['player_reference_id']) if row.get('player_reference_id') else None,
                team_defencemen_on_ice_refs=_parse_refs(row.get('team_defencemen_on_ice_refs')),
                grade=row.get('expected_goals_all_shots_grade'),
                raw=dict(row),
            )
            for row in rows
        ]

        return Game(info=info, events=events, toi=toi, roster=roster)

    finally:
        cursor.close()
