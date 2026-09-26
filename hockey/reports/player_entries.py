#!/usr/bin/python
"""Zone entries and dump-ins per player, on-ice, over a season.

The second report, and the point of :mod:`hockey.reports.on_ice` being
parameterised: this file is a list of columns and a name. No fetching, no
drawing, no metric definitions -- the lanes below are
``hockey/derive/metric_catalog.py``'s and are counted with its predicates.

EVERY COLUMN IS "FOR": the entries and dump-ins the player's OWN team made
while he was on the ice. The engine splits by the event's team, so
``AGAINST`` would give the same lanes from the opponent's side -- entries
conceded -- which is a different report and not this one.

WHAT THE FIVE COLUMNS ARE, in the catalog's own vocabulary:

* Successful controlled entries -- ``Controlled entries · Successful``.
* ...with a play after -- Result AND With-Play-After, two lanes from two
  filter groups, which the engine ANDs. Per the module's own notes a carry
  into the zone is always 'successful', and it is the play after that
  separates an entry that went somewhere from one that did not.
* ...with a shot -- Result AND (With Shot On Net OR With Slot Shot). Two lanes
  of ONE group, which the engine ORs. That union is exactly the complement of
  'With No Shot': checked over three games, 50 on-net and 37 slot shots union
  to 58, and 134 - 76 'With No Shot' is 58 as well. The two positive items
  overlap deliberately, the same convention as shooting's 'Slot'.
* Dump-ins -- ``Dump-ins · Successful``, so that it and the recovery column
  sit on the same footing and their ratio reads as a recovery rate.

  Be careful what that ratio means. A dump-in's 'successful' is NOT "we got it
  back" -- per this module's own CLAUDE.md it is some depth criterion, probably
  past the last defender, and the event that says the dumping team recovered is
  ``dumpinentry``, which is 1:1 with ``dumpin`` and is not a filtered
  population. So Recoveries ÷ Dump-ins is "recoveries per dump-in that got in
  deep", not a probability, and it is not bounded by 1.
* Successful dump-in recoveries -- Result AND Recovering-Team, because a
  "dump-in recovery" in this repo means the DUMPING team got the puck back.
  That is what ``dumpins.dumpin_recovery()`` has always returned
  (``is_offensive_recovery``), and the catalog carries the same predicate as
  ``Dump-in recoveries · Offensive``.

  Narrowing it matters, and the two halves are not the same axis. ``side=FOR``
  says the RECOVERING team was the player's -- verified: on all 198 recoveries
  over three games, ``event.team_id`` is the team of the player credited with
  the recovery. ``Offensive`` says the recovering team was also the DUMPING
  team. Without it the column counted his team retrieving anybody's dump-in,
  the opponent's included, which is a defensive stat wearing an offensive
  name -- and it showed: more recoveries per 60 than his team had dump-ins.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hockey.reports.on_ice import (FOR, AGAINST, Column, ColumnSet, EVEN_STRENGTH,
                                   REGULAR, open_connection, output_path,
                                   player_rows, to_sheet)
from hockey.reports.sheet import render_pdf

ENTRIES = "Controlled entries"
RECOVERIES = "Dump-in recoveries"

#: The report, in one place. Lanes from the same filter group are alternatives
#: (OR); lanes from different groups must both hold (AND) -- the metric layer's
#: own contract, so nothing here restates a predicate.
COLUMNS = ColumnSet((
    Column("Entries", f"{ENTRIES} · Successful", FOR),
    Column("w/ play", (f"{ENTRIES} · Successful",
                       f"{ENTRIES} · With Play After"), FOR),
    Column("w/ shot", (f"{ENTRIES} · Successful",
                       f"{ENTRIES} · With Shot On Net",
                       f"{ENTRIES} · With Slot Shot"), FOR),
    Column("Dump-ins", "Dump-ins · Successful", FOR),
    Column("Recoveries", (f"{RECOVERIES} · Successful",
                          f"{RECOVERIES} · Offensive"), FOR),
))

_NOTE = ("All columns are the player's own team's play while he was on the "
         "ice. \"w/ shot\" is an entry followed by a shot on net or a slot "
         "shot, which together are every entry not tagged 'With No Shot'. "
         "Recoveries are the dumping team's own (Offensive), matching "
         "dumpins.dumpin_recovery().")


def player_entries_report(players: Iterable, league: int, season: str, *,
                          output: Path | str | None = None,
                          context=EVEN_STRENGTH,
                          stage: str | None = REGULAR,
                          min_toi: float = 0.0,
                          conn=None,
                          title: str | None = None) -> Path:
    """Write the entries report for ``players`` and return the path written.

    Three steps, deliberately visible: compute the numbers, lay them out as a
    sheet, render the sheet. Nothing but :data:`COLUMNS` and the naming is
    specific to this report.
    """
    import time

    t=time.time()
    opened = conn is None
    conn = conn or open_connection()
    try:
        rows, missing = player_rows(conn, players, league, season,
                                    columns=COLUMNS, context=context,
                                    stage=stage, min_toi=min_toi)
    finally:
        if opened:
            conn.close()
    print(time.time() - t)
    sheet = to_sheet(rows, missing, columns=COLUMNS,
                     title=title or "Entries and dump-ins — even strength",
                     league=league, season=season, stage=stage,
                     context=context, min_toi=min_toi, note_extra=_NOTE)
    return render_pdf(sheet, output or output_path("player_entries", league,
                                                   season, stage))


if __name__ == "__main__":
    LEAGUE = 17
    SEASON = "20252026"
    PLAYERS = [24417, 22782, "Tom Hedberg", "Zach Wytinck", "Jonathan Wikström",
               "Carl Wäng", "Linus Skager"]

    import time
    started = time.perf_counter()
    path = player_entries_report(PLAYERS, LEAGUE, SEASON, min_toi=20.0)
    print(f"{path}  ({time.perf_counter() - started:.1f}s)")
