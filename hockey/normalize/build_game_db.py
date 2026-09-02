from __future__ import annotations

from hockey.model.events import Event
from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.model.roster import Player, Roster
from hockey.model.toi import ToIInterval


def _maybe_int(x) -> int | None:
    """The supplier's event ids are strings, and derived ones are not numeric."""
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def build_game_from_db(game_sl_id: int, conn, *, compiled: bool = False) -> Game:
    """Reconstruct a Game by querying the database (no JSON files required).

    ``compiled`` selects which event table to read, mirroring the two
    playsequence files on the JSON path:

      False → `event`, the playsequence.json vocabulary (~26 event types)
      True  → `compiled_event`, the playsequence_compiled.json vocabulary
              (~42 types: controlledentry, zoneexit, scoringchance, …) with
              the on-ice rosters and expected goals folded in by the ingest

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
            # The JSON path carries an ISO date string; the column is a datetime.
            date=scheduled_time.date().isoformat() if scheduled_time else None,
            stage=stage,
            home_final_score=home_goals,
            away_final_score=away_goals,
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
        table = "compiled_event" if compiled else "event"
        dict_cursor = conn.cursor(dictionary=True)
        try:
            dict_cursor.execute(
                f"SELECT * FROM {table} WHERE game_id = %s ORDER BY game_time",
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

        def _common(row: dict, team_col: str, player_col: str) -> dict:
            """The fields both tables spell the same way, minus their id columns."""
            return dict(
                game_id=game_id,
                t=float(row['game_time']),
                type=row.get('type') or "",
                name=row.get('name') or "",
                team_id_in_possession=team_db_to_sl.get(row['team_in_possession']) if row.get('team_in_possession') else None,
                team_id=team_db_to_sl.get(row[team_col]) if row.get(team_col) else None,
                player_id=player_db_to_sl.get(row[player_col]) if row.get(player_col) else None,
                team_defencemen_on_ice_refs=_parse_refs(row.get('team_defencemen_on_ice_refs')),
                team_forwards_on_ice_refs=_parse_refs(row.get('team_forwards_on_ice_refs')),
                opposing_team_forwards_on_ice_refs=_parse_refs(row.get('opposing_team_forwards_on_ice_refs')),
                opposing_team_defencemen_on_ice_refs=_parse_refs(row.get('opposing_team_defencemen_on_ice_refs')),
                grade=row.get('expected_goals_all_shots_grade'),
                play_section=row.get('play_section'),
                expected_goals_all_shots=row.get('expected_goals_all_shots'),
                expected_goals_on_net=row.get('expected_goals_on_net'),
                expected_goals_on_net_grade=row.get('expected_goals_on_net_grade'),
                raw=dict(row),
            )

        if compiled:
            events = [
                Event(
                    **_common(row, 'team_id', 'player_id'),
                    # sl_event_id is the supplier's id; derived events carry a
                    # composite one ("5453663996-314651935") that isn't an int,
                    # exactly as normalize_playsequence leaves it.
                    event_id=_maybe_int(row.get('sl_event_id')),
                    base_event_id=_maybe_int(row.get('sl_base_event_id')),
                )
                for row in rows
            ]
        else:
            events = [
                Event(
                    **_common(row, 'team', 'player_reference_id'),
                    team_goalie_on_ice_ref=player_db_to_sl.get(row['team_goalie_on_ice_ref']) if row.get('team_goalie_on_ice_ref') else None,
                    opposing_team_goalie_on_ice_ref=player_db_to_sl.get(row['opposing_team_goalie_on_ice_ref']) if row.get('opposing_team_goalie_on_ice_ref') else None,
                )
                for row in rows
            ]

        return Game(info=info, events=events, toi=toi, roster=roster)

    finally:
        cursor.close()
