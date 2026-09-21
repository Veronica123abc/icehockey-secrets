"""Cross-game roster queries against the v2 schema.

The third of the bulk readers, beside ``event_query`` (which events) and
``shift_query`` (over how much ice time). This one answers WHO: name, team and
position per player per game, as the :class:`~hockey.model.roster.Roster` the
model layer already passes around::

    rosters = query_rosters(conn, game_sl_ids=[186449, 186461])
    rosters[186449].players[9861].position      # 'C'

POSITION IS A FACT ABOUT A GAME, not about a player, which is why this is keyed
by game and not flattened. `affiliation` carries one row per player per game,
so a player loaned mid-season has the right team in each game rather than one
answer for the season.

WHY IT EXISTS SEPARATELY. Three callers were each spelling the same join --
``build_game_db``, ``skater.py``'s database adapter and now the reports layer.
Anything that classifies a SITUATION needs it: the manpower behind 5v4 is a
count of skaters, so a goalie has to be recognisable as one, and `shift` alone
cannot say which of six intervals is the goalie's.

Nothing here touches the filesystem, so it imports without DATA_ROOT_DIR.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from hockey.model.roster import Player, Roster


def _placeholders(values: Sequence) -> str:
    return ', '.join(['%s'] * len(values))


def query_rosters(conn, *,
                  game_sl_ids: Iterable[int] | None = None,
                  league_sl_id: int | None = None,
                  season: str | None = None) -> dict[int, Roster]:
    """game id -> that game's :class:`Roster`. All ids are SportLogIQ ids.

    The filters mirror the other two readers and combine with AND. Asking for
    nothing returns every game in the database, which is rarely what anyone
    wants -- narrow by games, or by league and season.
    """
    where: list[str] = []
    params: list = []
    if game_sl_ids is not None:
        game_sl_ids = [int(g) for g in game_sl_ids]
        if not game_sl_ids:
            return {}
        where.append(f"g.sl_id IN ({_placeholders(game_sl_ids)})")
        params.extend(game_sl_ids)
    if league_sl_id is not None:
        where.append("g.league_id = (SELECT id FROM league WHERE sl_id = %s)")
        params.append(league_sl_id)
    if season is not None:
        where.append("g.season = %s")
        params.append(season)

    sql = ("""SELECT g.sl_id, p.sl_id, t.sl_id, p.first_name, p.last_name,
                     a.position
              FROM affiliation a
              JOIN game g ON g.id = a.game_id
              JOIN player p ON p.id = a.player_id
              LEFT JOIN team t ON t.id = a.team_id"""
           + (f" WHERE {' AND '.join(where)}" if where else ""))

    players_by_game: dict[int, dict[int, Player]] = {}
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        for game_sl, player_sl, team_sl, first, last, position in cursor.fetchall():
            players_by_game.setdefault(int(game_sl), {})[player_sl] = Player(
                player_id=player_sl, team_id=team_sl, first_name=first,
                last_name=last, position=position)
    finally:
        cursor.close()

    return {game_sl: Roster(game_id=game_sl, players=players)
            for game_sl, players in players_by_game.items()}


def player_names(rosters: Iterable[Roster]) -> dict[int, tuple[str, str]]:
    """player id -> (display name, position), taking the last game seen.

    A convenience for anything reporting across games, where the name is the
    same every time and the position is what the player was listed as most
    recently in the set given.
    """
    out: dict[int, tuple[str, str]] = {}
    for roster in rosters:
        for player_id, player in roster.players.items():
            first = (player.first_name or "").strip()
            last = (player.last_name or "").strip()
            out[player_id] = (" ".join(p for p in (first, last) if p)
                              or str(player_id), player.position or "")
    return out
