from __future__ import annotations

from collections import Counter

from hockey.model.roster import Player


def get_roster(team_id: int, season: str, conn=None) -> list[Player]:
    """Every player who dressed for team ``team_id`` (SportLogIQ id) in ``season``.

    One :class:`Player` per player, ordered by SportLogIQ id. Position and
    jersey number belong to an affiliation, i.e. to one game, so a player who
    switched between games gets the one he wore most often.

    ``conn`` is an open database connection; without one, a connection is
    opened and closed here.
    """
    owned = conn is None
    if owned:
        from hockey.db.database import open_database_azure
        conn = open_database_azure()

    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT p.sl_id, p.first_name, p.last_name, p.laterality,
                      a.position, a.jersey_number
               FROM affiliation a
                        JOIN player p ON p.id = a.player_id
                        JOIN game g ON g.id = a.game_id
                        JOIN team t ON t.id = a.team_id
               WHERE t.sl_id = %s
                 AND g.season = %s""",
            (int(team_id), str(season)))
        rows = cursor.fetchall()
    finally:
        cursor.close()
        if owned:
            conn.close()

    names: dict[int, tuple] = {}
    positions: dict[int, Counter] = {}
    jerseys: dict[int, Counter] = {}
    for sl_id, first, last, shoots, position, jersey in rows:
        player_id = int(sl_id)
        names[player_id] = (first, last, shoots)
        positions.setdefault(player_id, Counter())[position] += 1
        jerseys.setdefault(player_id, Counter())[jersey] += 1

    return [Player(player_id=player_id, team_id=int(team_id),
                   first_name=first, last_name=last,
                   position=positions[player_id].most_common(1)[0][0],
                   shoots=shoots,
                   jersey_number=jerseys[player_id].most_common(1)[0][0])
            for player_id, (first, last, shoots) in sorted(names.items())]
