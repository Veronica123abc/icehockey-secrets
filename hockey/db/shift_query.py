"""Cross-game shift queries against the v2 schema.

The counterpart to ``event_query.py``, and the other half of a rate. That
module answers "which events", as ``Event`` objects; this one answers "over how
much ice time", as ``ToIInterval`` objects -- the same dataclass
``Game.toi`` carries, so anything that already consumes shifts consumes these::

    shifts = query_shifts(conn, league_sl_id=17, season="20252026",
                          player_sl_ids=24417)
    minutes = toi_seconds(shifts)[24417] / 60      # 1377.9 over 65 games

A shift is the ONLY record of ice time in the v2 schema -- `event` has no
duration and no on-ice columns -- so every TOI question, and every per-60,
comes through here.

THE FILTERS MIRROR ``query_events``: league, season, game ids, player, team.
Coarse enough for the database to answer with an index; anything finer stays in
Python. ``player_sl_ids`` takes one id or many, since asking for a line or a
pairing is as common as asking for one skater.

GOALIES ARE IN THE SHIFT DATA -- 3156 intervals, seven or eight a game -- so
``include_goalies=False`` is offered here rather than left to every caller to
remember. ``skater.py`` drops them through the roster; this drops them through
`affiliation.position`, which is the same fact read from the table that already
has to be joined for ``team_id``.

WHAT THIS DOES NOT DO: narrow by SITUATION. A shift carries no manpower or
goalie field -- it is an interval, not an event -- so ES ice time cannot be a
WHERE clause. It is computed by cutting every shift at each on/off boundary and
classifying the slices, which ``hockey/metrics/player/skater.py`` already does
(``_situation_timeline`` / ``_selected_seconds``) and this module deliberately
does not repeat. Use :func:`toi_seconds` for a whole-game denominator, and
``skater_stats(..., context=...)`` when the numerator is narrowed by context,
so both halves are narrowed the same way.

Settings are NOT resolved at import (unlike ``event_query``, which does and so
cannot be imported without DATA_ROOT_DIR). Nothing here touches the filesystem.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from hockey.model.toi import ToIInterval, merge_spans

#: Roster position marking a goalie, as `affiliation.position` spells it.
GOALIE = "G"


def _placeholders(values: Sequence) -> str:
    return ', '.join(['%s'] * len(values))


def _as_id_list(value: int | Iterable[int] | None) -> list[int] | None:
    """One id, many ids, or None -- always a list or None."""
    if value is None:
        return None
    if isinstance(value, int):
        return [value]
    return [int(v) for v in value]


def query_shifts(conn, *,
                 league_sl_id: int | None = None,
                 season: str | None = None,
                 game_sl_ids: Iterable[int] | None = None,
                 player_sl_ids: int | Iterable[int] | None = None,
                 team_sl_id: int | None = None,
                 include_goalies: bool = True,
                 limit: int | None = None) -> list[ToIInterval]:
    """Shifts matching the coarse filters, as :class:`ToIInterval` objects.

    All ids are SportLogIQ ids, matching the rest of the model layer.
    ``game_id`` on the returned intervals is the game's SportLogIQ id, so they
    line up with ``Event.game_id`` from :func:`~hockey.db.event_query
    .query_events` without translation.

    ``team_id`` comes from `affiliation`, which is what makes it the team the
    player was ROSTERED for in that game -- a player who changes team mid-season
    carries the right one per game rather than one fact for the list.

    An unknown player or team id returns no shifts, the same way
    ``query_events`` returns no events: a typo reads as an empty result, not as
    an unfiltered one.
    """
    player_sl_ids = _as_id_list(player_sl_ids)
    game_sl_ids = _as_id_list(game_sl_ids)

    where: list[str] = []
    params: list = []

    if league_sl_id is not None:
        where.append("g.league_id = (SELECT id FROM league WHERE sl_id = %s)")
        params.append(league_sl_id)
    if season is not None:
        where.append("g.season = %s")
        params.append(season)
    if game_sl_ids:
        where.append(f"g.sl_id IN ({_placeholders(game_sl_ids)})")
        params.extend(game_sl_ids)
    if player_sl_ids:
        where.append(f"p.sl_id IN ({_placeholders(player_sl_ids)})")
        params.extend(player_sl_ids)
    if team_sl_id is not None:
        where.append("t.sl_id = %s")
        params.append(team_sl_id)
    if not include_goalies:
        # LEFT JOINed, so spell out the null case rather than relying on every
        # shift having an affiliation row -- they all do today, and a missing
        # one should read as "not known to be a goalie", not as a goalie.
        where.append(f"(a.position IS NULL OR a.position <> %s)")
        params.append(GOALIE)

    sql = ("""SELECT g.sl_id, p.sl_id, t.sl_id, s.in_time, s.out_time
              FROM shift s
              JOIN game g ON g.id = s.game_id
              JOIN player p ON p.id = s.player_id
              LEFT JOIN affiliation a
                     ON a.game_id = s.game_id AND a.player_id = s.player_id
              LEFT JOIN team t ON t.id = a.team_id"""
           + (f" WHERE {' AND '.join(where)}" if where else "")
           + " ORDER BY g.sl_id, s.in_time")
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))

    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        return [
            ToIInterval(game_id=int(game_sl), team_id=team_sl,
                        player_id=player_sl, start_t=float(in_time),
                        end_t=None if out_time is None else float(out_time))
            for game_sl, player_sl, team_sl, in_time, out_time in cursor.fetchall()
        ]
    finally:
        cursor.close()


def toi_seconds(shifts: Iterable[ToIInterval]) -> dict[int, float]:
    """player id -> seconds on the ice, summed over whatever games are given.

    Overlapping shifts of one player in one game are merged rather than added
    by ``toi.merge_spans``, the same arithmetic ``skater._skater_spans`` uses.
    What differs from that function is policy, not maths: it drops goalies by
    roster (here that is ``include_goalies=False`` on the query) and closes an
    open shift at the end of ITS game, whereas an open shift here
    (``end_t is None``, zero rows in the database today) is closed at the last
    time seen in the same game AMONG THE SHIFTS GIVEN -- the same rule only
    when the caller passed the whole game.
    """
    by_player_game: dict[tuple[int, int], list[tuple[float, float | None]]] = {}
    end_of_game: dict[int, float] = {}
    for shift in shifts:
        by_player_game.setdefault((shift.player_id, shift.game_id), []).append(
            (shift.start_t, shift.end_t))
        if shift.end_t is not None:
            end_of_game[shift.game_id] = max(
                end_of_game.get(shift.game_id, 0.0), shift.end_t)

    out: dict[int, float] = {}
    for (player_id, game_id), spans in by_player_game.items():
        closed = [(start, end if end is not None
                   else end_of_game.get(game_id, start))
                  for start, end in spans]
        out[player_id] = out.get(player_id, 0.0) + sum(
            end - start for start, end in merge_spans(closed))
    return out


def games_played(shifts: Iterable[ToIInterval]) -> dict[int, int]:
    """player id -> how many distinct games he has a shift in.

    The honest denominator for a per-game figure: a player appears here only
    for games he actually took a shift in, which is not the same as the games
    an EVENT list covers -- a game where he recorded none of the event being
    counted is in this and not in that.
    """
    seen: dict[int, set[int]] = {}
    for shift in shifts:
        seen.setdefault(shift.player_id, set()).add(shift.game_id)
    return {player_id: len(games) for player_id, games in seen.items()}


if __name__ == "__main__":
    # Hardcoded so this runs from the IDE's run/debug button with no arguments,
    # the same way event_query.py does. Edit these and step in.
    LEAGUE_SL_ID = 17
    SEASON = "20252026"
    GAME_SL_IDS = None            # or a list, INSTEAD of league+season
    PLAYER_SL_IDS = [24417]       # one id or several; None for every player
    TEAM_SL_ID = None
    INCLUDE_GOALIES = False
    LANE_KEY = "Shots · 1-Timer Taken"   # the numerator, from the metric catalog

    import time
    from pathlib import Path

    from hockey.config.settings import Settings
    from hockey.db import database

    try:
        # Only for the .env side effect -- this module needs no DATA_ROOT_DIR,
        # and from_env raises rather than shrugging when it is unset.
        Settings.from_env(project_root=Path(__file__).resolve().parent)
    except ValueError:
        pass

    conn = database.open_database_azure()
    try:
        started = time.perf_counter()
        shifts = query_shifts(
            conn,
            league_sl_id=LEAGUE_SL_ID,
            season=SEASON,
            game_sl_ids=GAME_SL_IDS,
            player_sl_ids=PLAYER_SL_IDS,
            team_sl_id=TEAM_SL_ID,
            include_goalies=INCLUDE_GOALIES,
        )
        elapsed = time.perf_counter() - started

        print(f"{len(shifts):,} shifts in {elapsed*1000:.0f} ms "
              f"across {len({s.game_id for s in shifts})} games")

        seconds = toi_seconds(shifts)
        played = games_played(shifts)
        print(f"\n{'player':>8s} {'GP':>4s} {'TOI':>9s} {'TOI/GP':>8s}")
        for player_id, total in sorted(seconds.items(), key=lambda kv: -kv[1])[:10]:
            games = played[player_id]
            print(f"{player_id:8d} {games:4d} {total/60:8.1f}m "
                  f"{total/60/games:7.1f}m")

        # The point of the module: the other half of a per-60. The numerator is
        # a metric catalog lane over the matching events; the denominator is
        # the ice time those events had to happen in.
        if PLAYER_SL_IDS and len(PLAYER_SL_IDS) == 1:
            from hockey.db.event_query import query_events
            from hockey.derive import metric_catalog as mc

            player_id = PLAYER_SL_IDS[0]
            events = query_events(conn, league_sl_id=LEAGUE_SL_ID, season=SEASON,
                                  game_sl_ids=GAME_SL_IDS,
                                  player_sl_id=player_id,
                                  names=[mc.BY_KEY[LANE_KEY].event_name])
            lane = mc.BY_KEY[LANE_KEY]
            n = sum(1 for e in events
                    if e.name == lane.event_name and lane.matches(e))
            hours = seconds[player_id] / 3600
            print(f"\n{LANE_KEY}: {n} in {hours*60:.1f} min "
                  f"= {n / hours:.2f} per 60")
            # The event list covers only games the lane fired in; the shifts
            # cover every game played. Rating one against the other is the
            # point -- the two game counts differing is expected, not a bug.
            print(f"   events cover {len({e.game_id for e in events})} games, "
                  f"shifts cover {played[player_id]}")
    finally:
        conn.close()
