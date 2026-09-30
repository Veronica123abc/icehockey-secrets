#!/usr/bin/python
'''
Output: A pdf report with one player on each line with columns for a set of metrics counted when the player was on the ice.
Only events during even strength should be counted for each player
Input: a list of players, a league and a season
The following metrics should be included:

1.Games Played (whith Total Time on Ice (TOI) > 0 s)

2. Total TOI
3. TOI / game
4. Goals for / 60min
5. Goals against / 60min
6. Expected Goals for / 60min
7. Expected Goals against / 60min
8. Shot Attempts for / 60min
9. Shots On Goal for / 60min
10. Shots from slot for / 60min
11. Shot Attempts against / 60min
12. Shots on Goals against / 60min
13. Shots from slot against / 60min
---

The thirteen columns above, as a declaration. Everything that turns them into a
PDF -- which games, which situation, who was on the ice, the page itself -- is
:mod:`hockey.reports.on_ice`, and is shared with every other report in this
package. What is specific to THIS report is :data:`COLUMNS` and nothing else.

Each column names lanes of ``hockey/derive/metric_catalog.py`` and is counted
with those lanes' own predicates, so "shots on goal" means here what it means
on the game canvas rail. The report is the canvas's player report with the
lanes fixed, the situation fixed at even strength, and the game count raised
from one to a season.

TIED TO THE SUPPLIER'S PUBLISHED NUMBERS. Player 24417, league 17, 2025/26:
934 even-strength minutes, 37 on-ice goals for, 914 shot attempts for, against
934.5 / 37 / 914 here. The three selection choices that reconcile them --
stage, what even strength means, and strict shift containment -- are documented
where they are made, in ``on_ice.py``.

Checked against the supplier for EVERY skater in that league season, not just
that one, by ``hockey/regression/supplier.py``: shot attempts 155,464 against
their 155,682, on-ice goals 6,977 against 6,981, and 414 of 429 players inside
a single event. Re-run it after changing anything here.

xG SUMS THE PUBLISHED VALUE, NOT THE RAW ONE -- ``weight="xg_official"``. The
supplier raises every ungraded slot shot to a grade C chance downstream of the
event feed, so summing the feed's own number lands 2.2% low. See
:func:`~hockey.metrics.on_ice._xg_official`.
'''
from __future__ import annotations
from hockey.reports.helpers.get_roster import get_roster
from collections.abc import Iterable
from pathlib import Path

from hockey.reports.on_ice import (AGAINST, FOR, Column, ColumnSet,
                                   EVEN_STRENGTH, REGULAR, open_connection,
                                   output_path, player_rows, to_sheet)
from hockey.reports.sheet import render_pdf

#: The report, in one place. Adding a column means adding a lane key here --
#: there is nothing else to change.
#:
#: The two leading BOTH columns are undivided totals rather than rates: they
#: are the arithmetic the rest of the row is built on, printed so it can be
#: checked. G (woi) must equal the goals scored by either team while the player
#: was on the ice, and SA (woi) the shot attempts -- both countable from the
#: events directly, and both what the canvas shows for one game.
COLUMNS = ColumnSet((
    #Column("G (woi)",  "Goals · All", BOTH, rate=False),
    #Column("SA (woi)", "Shots · All", BOTH, rate=False),
    Column("G",    "Goals · All",    FOR),
    Column("xG",   "Shots · All",    FOR,     weight="xg_official"),
    Column("SA",   "Shots · All",    FOR),
    Column("SOG",  "Shots · On Net", FOR),
    Column("Slot", "Shots · Slot",   FOR),
    Column("G",    "Goals · All",    AGAINST),
    Column("xG",   "Shots · All",    AGAINST, weight="xg_official"),
    Column("SA",   "Shots · All",    AGAINST),
    Column("SOG",  "Shots · On Net", AGAINST),
    Column("Slot", "Shots · Slot",   AGAINST),
))

_NOTE = ("xG is the supplier's expected_goals_all_shots summed over shot "
         "attempts, with ungraded slot shots raised to a grade C chance as "
         "the supplier's own published figures do; SOG includes goals; Slot "
         "is inner + outer slot.")


def player_woi_report(players: Iterable, league: int, season: str, *,
                      output: Path | str | None = None,
                      context=EVEN_STRENGTH,
                      stage: str | None = REGULAR,
                      min_toi: float = 0.0,
                      conn=None,
                      title: str | None = None) -> Path:
    """Write the on-ice report for ``players`` and return the path written.

    Three steps, deliberately visible: compute the numbers, lay them out as a
    sheet, render the sheet. Nothing but :data:`COLUMNS` and the naming is
    specific to this report. See :func:`hockey.reports.on_ice.player_rows` for
    what the arguments mean.
    """
    opened = conn is None
    conn = conn or open_connection()
    try:
        rows, missing = player_rows(conn, players, league, season,
                                    columns=COLUMNS, context=context,
                                    stage=stage, min_toi=min_toi)
    finally:
        if opened:
            conn.close()

    sheet = to_sheet(rows, missing, columns=COLUMNS,
                     title=title or "On-ice report — even strength",
                     league=league, season=season, stage=stage,
                     context=context, min_toi=min_toi, note_extra=_NOTE)
    return render_pdf(sheet, output or output_path("shooting_player_woi", league,
                                                   season, stage))


if __name__ == "__main__":
    LEAGUE = 17
    SEASON = "20252026"
    # Ids and names both work; the last one is a deliberate miss, so the
    # # "not in the table" footnote is visible in the demo output.
    # PLAYERS = [24417, 6970, "Tom Hedberg", "Zach Wytinck", "Jonathan Wikström",
    #            "Carl Wäng", "Linus Skager", "Nobody Atall"]

    PLAYERS = get_roster(1395,'20262027')

    import time
    started = time.perf_counter()
    path = player_woi_report(PLAYERS, LEAGUE, SEASON, min_toi=20.0)
    print(f"{path}  ({time.perf_counter() - started:.1f}s)")
