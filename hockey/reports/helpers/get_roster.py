from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hockey.reports.on_ice import open_connection


def get_roster(team_id:int, season:str):
    conn = open_connection()

    cursor = conn.cursor()
    query =         f"""SELECT DISTINCT p.sl_id
           FROM affiliation a
                    JOIN player p ON p.id = a.player_id
                    JOIN game g ON g.id = a.game_id
                    JOIN team t ON t.id = a.team_id
           WHERE t.sl_id = '{team_id}'
             AND g.season = '{season}'
           ORDER BY p.sl_id;"""

    cursor.execute(query)

    players = cursor.fetchall()
    PLAYERS = [k[0] for k in players]
    return PLAYERS