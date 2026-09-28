#!/usr/bin/python
"""Adapters that produce :class:`~hockey.model.game_data.GameData` bundles.

Where a game's events, shifts and roster come from, so that an aggregation
never has to ask. Three sources, one shape:

* :func:`from_games` wraps built ``Game`` objects, from files or anywhere.
* :func:`load_games` builds them from the local data root, one at a time.
* :func:`from_database` reads `event`, `shift` and `affiliation` in bulk.

ONLY THE FILE PATH STREAMS, and the difference matters when choosing one.
``load_games`` is a generator, so a consumer that iterates and drops holds
about one game: measured flat at ~73MB across 2, 4, 6, 8 and 10 games, against
162MB for the same six materialised into a list. ``from_database`` cannot do
that -- it issues its queries and buffers every game before yielding the first
bundle, so its peak scales with the season (365MB over 410 games). What it
buys instead is speed: a handful of bulk statements rather than ~0.9s and
~23MB of game-building each, 17.6s for a 410-game season.

A GAME THE DATABASE DOES NOT HOLD IS SKIPPED AND NAMED, not quietly read from
files: a silent fallback would make a season's numbers depend on which machine
ran it. "Holds" means events AND shifts, because events alone would produce a
full set of counts against no ice time.
"""
from __future__ import annotations

import warnings
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence

from hockey.model.events import Event
from hockey.model.game_data import GameData
from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval


def from_games(games: Iterable) -> Iterator[GameData]:
    """Adapt built ``Game`` objects. Lazy, so the games stream."""
    for game in games:
        yield GameData.from_game(game)


def available_games(conn, game_sl_ids: Iterable[int]) -> tuple[list[int], list[int]]:
    """``(usable, missing)`` for the ids asked for, in the order given.

    Usable means the database holds BOTH events and shifts for the game. A
    game row on its own is not enough: counts with no ice time behind them
    would look like a very idle player rather than like missing data.
    """
    game_sl_ids = list(dict.fromkeys(game_sl_ids))
    if not game_sl_ids:
        return [], []
    placeholders = ", ".join(["%s"] * len(game_sl_ids))
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""SELECT g.sl_id,
                       EXISTS(SELECT 1 FROM event e WHERE e.game_id = g.id),
                       EXISTS(SELECT 1 FROM shift s WHERE s.game_id = g.id)
                FROM game g WHERE g.sl_id IN ({placeholders})""",
            tuple(game_sl_ids))
        complete = {int(sl) for sl, has_events, has_shifts in cursor.fetchall()
                    if has_events and has_shifts}
    finally:
        cursor.close()
    usable = [g for g in game_sl_ids if g in complete]
    missing = [g for g in game_sl_ids if g not in complete]
    return usable, missing


def from_database(conn, game_sl_ids: Iterable[int], *,
                  names: Sequence[str] | None = None) -> Iterator[GameData]:
    """Bundles read straight from the database, in bulk rather than per game.

    The whole set costs ``6 + ceil(total_events / 5000)`` statements: one
    availability check, one for the events, two id maps, one per 5000-event
    chunk of `event_flag` (``_CHUNK`` in hockey/db/event_query.py), then one
    each for shifts and affiliation. Seven for eight games, sixteen for a
    410-game season. So it grows with event VOLUME rather than with the number
    of games -- but it does grow, and calling it a fixed number would be
    wrong; the point is that nothing here is per game.

    ``names`` narrows the fetch to the supplier event names the caller counts,
    which is most of why this is quick; None fetches every event of the games,
    which is rarely what anyone wants over a season.

    Games the database does not hold are skipped and named in a warning --
    see the module docstring for why they are not quietly read from files.

    Deliberately NOT a generator. Which games are missing is settled when you
    call this, not when something first iterates it, so the warning names the
    caller who passed the ids rather than whatever loop happened to consume
    them -- and it arrives even if the result is never iterated at all. The
    reading is still deferred to first iteration; it is the checking that is
    eager. Deferred is not incremental, though: once iteration does start,
    every query runs before the first bundle comes back, so the memory note in
    the module docstring applies from that point on.
    """
    usable, missing = available_games(conn, game_sl_ids)
    if missing:
        warnings.warn(
            f"{len(missing)} game(s) not in the database, skipped: "
            f"{', '.join(str(g) for g in missing)}",
            stacklevel=2)
    return _database_bundles(conn, usable, names)


def _database_bundles(conn, usable: Sequence[int],
                      names: Sequence[str]) -> Iterator[GameData]:
    """The reading half of :func:`from_database`, once the ids are settled.

    ``query_events`` and ``query_shifts`` are imported here rather than at the
    top because ``hockey.db.event_query`` resolves Settings at import time, and
    this module is meant to stay importable without DATA_ROOT_DIR.
    ``shift_query`` has no such problem; it is imported alongside for symmetry.
    """
    if not usable:
        return
    from hockey.db.event_query import query_events
    from hockey.db.roster_query import query_rosters
    from hockey.db.shift_query import query_shifts

    events_by_game: dict[int, list[Event]] = defaultdict(list)
    for event in query_events(conn, game_sl_ids=usable,
                              names=list(names) if names else None):
        events_by_game[event.game_id].append(event)

    # Shifts come back already in SportLogIQ ids -- the space the events, the
    # roster and GameData.game_id all speak -- so grouping them is all that is
    # left to do here. Goalies are kept: _skater_spans drops them by roster,
    # and _situation_timeline needs them to tell a pulled goalie from a
    # penalty.
    toi_by_game: dict[int, list[ToIInterval]] = defaultdict(list)
    for interval in query_shifts(conn, game_sl_ids=usable):
        toi_by_game[interval.game_id].append(interval)

    # The roster is the third bulk read, and it is `affiliation` rather than
    # either of the other two tables -- who was dressed, and as what.
    rosters = query_rosters(conn, game_sl_ids=usable)
    empty = Roster(game_id=0, players={})

    for game_sl in usable:
        yield GameData(
            game_id=game_sl,
            events=events_by_game.get(game_sl, []),
            toi=toi_by_game.get(game_sl, []),
            roster=rosters.get(game_sl, empty))


def load_games(game_ids: Iterable[int], *,
               playsequence_source: str = "playsequence_compiled") -> Iterator:
    """Build Games from the local data root, one at a time.

    A generator on purpose: a built game retains ~23MB, so materialising a
    52-game season would hold ~1.2GB for no reason. Consumed by
    :func:`from_games`, the peak stays at about one game.
    """
    from pathlib import Path
    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
    for game_id in game_ids:
        yield build_game(RawGame(game_id=game_id, root_dir=settings.data_root_dir,
                                 playsequence_source=playsequence_source))
