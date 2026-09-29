"""Which games -- the schedule query, against the v2 schema.

The fourth bulk reader, beside ``event_query`` (which events), ``shift_query``
(over how much ice time) and ``roster_query`` (who played). This one answers
the question the other three take as an argument: WHICH GAMES::

    ids = query_game_ids(conn, league_sl_id=17, season="20252026")   # 364
    team_rows(conn, games=ids[-20:], columns=COLUMNS)                # last 20

A GAME LIST IS THE UNIT OF WORK for everything in ``hockey/metrics``. Cost
there is linear in distinct games, and a report over part of a season -- a
month, a team's last twenty, the games since a coaching change -- is the same
computation over a shorter list. So the list is built here, once, and passed
in, rather than each caller re-deriving it from data it then throws away.

WHY NOT DERIVE IT FROM THE SHIFTS. That was the earlier answer, and it read
281,513 shift rows to learn 364 game ids -- 2.5 seconds to produce a list the
`game` table hands over in milliseconds off `game_league_season`. The shifts
have to be read anyway for the games that are kept; they should not also be
read for the ones that are not.

A NULL STAGE COUNTS AS REGULAR SEASON. That is an ingestion gap, not a third
kind of game: league 17's 2025/26 has two of them, 186449 and 186461, and the
schedule manifest gives both as 'regular'. Leaving them out put a reference
player 16 even-strength minutes short of the supplier's published season. If
preseason games ever arrive with a null stage, this is where that breaks.

``played_only`` is on by default because the schedule runs ahead of the data:
329 of the rows in `game` are 'upcoming'. Including them costs nothing in
answers -- they have no events and no shifts -- but it pads every downstream
``IN`` clause with ids that can only return nothing.

Nothing here touches the filesystem, so it imports without DATA_ROOT_DIR.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

#: ``stage`` value for the regular season; the one that also admits NULL.
REGULAR = "regular"
PLAYOFFS = "playoffs"

#: `event_status` of a game that has been played.
FINISHED = "over"


def _placeholders(values: Sequence) -> str:
    return ', '.join(['%s'] * len(values))


def _as_id_list(value: int | Iterable[int] | None) -> list[int] | None:
    """One id, many ids, or None -- always a list or None."""
    if value is None:
        return None
    if isinstance(value, int):
        return [value]
    return [int(v) for v in value]


def query_game_ids(conn, *, league_sl_id: int | None = None,
                   season: str | None = None,
                   stage: str | None = REGULAR,
                   team_sl_ids: int | Iterable[int] | None = None,
                   since=None, until=None,
                   played_only: bool = True) -> list[int]:
    """The SportLogIQ ids of the games matching these filters.

    Ordered by scheduled time, earliest first, so a slice is a stretch of the
    season: ``[-20:]`` is the last twenty, ``[:41]`` the first half. Games with
    no scheduled time sort last rather than dropping out.

    ``stage`` defaults to the regular season, and that setting alone also
    admits a NULL stage -- see the module docstring. Pass ``stage=None`` for
    every stage, or ``PLAYOFFS`` for the exact value.

    ``team_sl_ids`` keeps a game if EITHER side is one of these teams, so one
    team gives its season and two give their season plus their head-to-heads.

    ``since`` / ``until`` bound `scheduled_time`; anything the driver accepts
    as a datetime works, including an ISO string. ``until`` is inclusive, so a
    date alone means midnight that morning.
    """
    where, params = [], []

    if league_sl_id is not None:
        where.append("g.league_id = (SELECT id FROM league WHERE sl_id = %s)")
        params.append(int(league_sl_id))
    if season is not None:
        where.append("g.season = %s")
        params.append(str(season))

    if stage == REGULAR:
        where.append("(g.stage = %s OR g.stage IS NULL)")
        params.append(REGULAR)
    elif stage is not None:
        where.append("g.stage = %s")
        params.append(str(stage))

    teams = _as_id_list(team_sl_ids)
    if teams:
        sub = f"SELECT id FROM team WHERE sl_id IN ({_placeholders(teams)})"
        where.append(f"(g.home_team_id IN ({sub}) OR g.away_team_id IN ({sub}))")
        params.extend(teams)
        params.extend(teams)

    if since is not None:
        where.append("g.scheduled_time >= %s")
        params.append(since)
    if until is not None:
        where.append("g.scheduled_time <= %s")
        params.append(until)
    if played_only:
        where.append("g.event_status = %s")
        params.append(FINISHED)

    sql = "SELECT g.sl_id FROM game g"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY g.scheduled_time IS NULL, g.scheduled_time, g.sl_id"

    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        return [int(row[0]) for row in cursor.fetchall()]
    finally:
        cursor.close()
