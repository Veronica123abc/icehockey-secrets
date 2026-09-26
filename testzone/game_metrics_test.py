#!/usr/bin/python
"""The metric catalog bound to some events: every lane, with its count.

``metric_catalog.py`` says what the lanes ARE; this says what they are worth
in a particular game. It is the game canvas's rail without the canvas -- the
same predicates, the same tree, the same numbers, printed instead of drawn::

    from hockey.derive.game_metrics import game_metrics

    metrics = game_metrics(game)           # a built Game
    metrics.print_tree()
    metrics.count("Shots · On Net")        # 61

EVENTS ARE THE PRIMITIVE, a game merely one way to get some. The counting
loop only ever reads ``event.name``, ``event.t`` and ``team_of(event)``, so
anything that yields Events works -- notably ``query_events``, whose results
may span a whole season, several players and both benches of every game::

    from hockey.db.event_query import query_events
    from hockey.derive.game_metrics import event_metrics

    events = query_events(conn, league_sl_id=17, season="20252026",
                          on_ice_player_sl_id=24417, with_on_ice=True)
    event_metrics(events).print_tree()

:func:`game_metrics` is a three-line wrapper over :func:`event_metrics` that
supplies the game's own events and labels its two teams home and away.

NO METRIC IS DEFINED HERE, and not one predicate is respelled. Classification
is ``catalog.lanes_for_event`` -- the single call the canvas makes -- so a lane
counts here exactly what it counts on the rail, in the reports and in the
golden snapshot. What this module adds is one pass, a Counter, and a printer.

IT PRINTS THE WHOLE TREE, INCLUDING EMPTY LANES. The canvas drops a lane with
no events, which is right for a rail you have to scroll but wrong for reading
the catalog: a zero is a fact about the game (this league tags no cross-ice
dump-ins) and its absence is indistinguishable from a lane that does not exist.
Pass ``hide_empty=True`` for the canvas's view.

TEAMS ARE COLUMNS, not a filter. ``team_of`` decides whose event it is -- the
same answer the reports' for/against split uses -- so the team columns sum to
the total except for events the supplier credits to nobody, which the footer
counts rather than hides. A game has two; an arbitrary event list may have
twenty, so the columns are dropped past ``max_team_columns`` rather than
printing a table nobody can read. Pass ``teams=[...]`` to pick which ones.

WHAT THIS IS NOT. There is no for/against here, and no ice time. Both need to
know whose team a PLAYER was on, which is a question about rosters and shifts
rather than about events -- ``hockey/reports/on_ice.py`` answers it.

A CONTEXT NARROWS BOTH THE COUNTS AND THE HEADER. ``context=None`` is every
situation, which is what makes the totals comparable to each module's own
``get_full_data``. Pass a ``ContextFilter`` and every lane is counted in that
situation instead, the way the canvas's context bar narrows its rail.

Run ``python -m hockey.derive.game_metrics`` to print one game.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from hockey.derive import context_filter as ctx
from hockey.derive import metric_catalog as catalog
from hockey.model.events import Event

# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings
from hockey.derive.game_metrics import game_metrics as game_metrics
from hockey.derive.game_metrics import event_metrics as event_metrics




def test():

        LEAGUE_SL_ID = 17
        SEASON = "20252026"
        PLAYER_SL_ID = 24417  # None for every player
        TEAM_SL_ID = None
        ON_ICE_PLAYER_SL_ID = 24417  # events while this player was on the ice
        NAMES = ["shot"]  # None for every event type
        OUTCOMES = None  # e.g. ["successful"]
        ZONES = None  # e.g. ["oz"]
        # True because the context filter below reads the goalie refs, which only
        # the on-ice reconstruction fills in. With it off they are all null, and
        # `goalies_of` cannot tell "unknown" from "off the ice" -- every event
        # classifies as 'Goalie out' and the default selection keeps none of them.
        # The pulled-goalie adjustment reads them too, so a handful of empty-net
        # events change PP2/PP1 with it on. Skater counts come from the row and
        # are there either way. It costs little: 0.4s for 388 events over 64 games.
        WITH_ON_ICE = True
        LIMIT = None
        LANE_KEY = "Shots · 1-Timer Taken"  # one leaf of the metric catalog

        # The situation to count that lane in. Spelled out rather than left to
        # ContextFilter's own defaults, which are ES with both goalies on the ice
        # -- a narrowing, not "everything", and an easy thing to apply by accident.
        CONTEXT_PERIODS = ["All"]  # or any of P1, P2, P3, OT
        CONTEXT_MANPOWER = ["ES", "PP1", "PP2"]  # of ES, SH1, SH2, PP1, PP2
        CONTEXT_GOALIES = ["Both goalies on ice"]  # or a goalie pulled, either end

        import time
        from collections import Counter

        from hockey.db import database
        from hockey.db.event_query import query_events
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
        except:
            print("error")


        print(len(events))

if __name__ == "__main__":
    #test()
    #exit(0)
    GAME_ID = 186451
    HIDE_EMPTY = False          # True for the canvas rail's view
    CONTEXT = None              # or ctx.DEFAULT for even strength

    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)
    metrics = game_metrics(build_game(raw), context=CONTEXT)
    metrics.print_tree(hide_empty=HIDE_EMPTY)