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
from hockey.helpers import get_roster
from hockey.metrics.on_ice import PlayerRow
from hockey.helpers.get_roster import get_roster
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
COLUMNS_FOR = ColumnSet((
    #Column("G (woi)",  "Goals · All", BOTH, rate=False),
    #Column("SA (woi)", "Shots · All", BOTH, rate=False),
    Column("G",    "Goals · All",    FOR),
   # Column("xG",   "Shots · All",    FOR,     weight="xg_official"),
   # Column("SA",   "Shots · All",    FOR),
   # Column("SOG",  "Shots · On Net", FOR),
   # Column("Slot", "Shots · Slot",   FOR),
   # Column("Inner\nSlot", "Shots · Inner Slot",   FOR),

))



num_col = len(COLUMNS_FOR.columns)
weights_for = {k.lanes[0]: 1 / num_col for k in COLUMNS_FOR.columns}

COLUMNS_AGAINST = ColumnSet((
    Column("G", "Goals · All", AGAINST),
    Column("xG", "Shots · All", AGAINST, weight="xg_official"),
    Column("SA", "Shots · All", AGAINST),
    Column("SOG", "Shots · On Net", AGAINST),
    Column("Slot", "Shots · Slot", AGAINST),
    Column("Inner\nSlot", "Shots · Inner Slot", AGAINST),
))

num_col = len(COLUMNS_AGAINST.columns)
weights_against = {k.lanes[0]: 1 / num_col for k in COLUMNS_AGAINST.columns}

WEIGHTS_AGAINST = [1/len(COLUMNS_AGAINST)] * len(COLUMNS_AGAINST) # Baseline - equal values


_NOTE = ("xG is the supplier's expected_goals_all_shots summed over shot "
         "attempts, with ungraded slot shots raised to a grade C chance as "
         "the supplier's own published figures do; SOG includes goals; Slot "
         "is inner + outer slot.")


def player_woi_data(columns: ColumnSet, players: Iterable, league: int, season: str, *,
                      output: Path | str | None = None,
                      context=EVEN_STRENGTH,
                      stage: str | None = REGULAR,
                      min_toi: float = 0.0,
                      conn=None,
                      title: str | None = None) -> Path:

    opened = conn is None
    conn = conn or open_connection()
    try:
        rows, missing = player_rows(conn, players, league, season,
                                    columns=columns, context=context,
                                    stage=stage, min_toi=min_toi)
    finally:
        if opened:
            conn.close()

    return rows


def weighted_contribution(player_woi_data: Iterable[PlayerRow], weights) -> Iterable[float]:

    res = {}
    for row in player_woi_data:
        contribution = 0
        for k in list(row.totals.keys()):
            contribution += 3600 * row.totals[k] * weights_for[k.split('|')[0]] / row.toi
        res[row.player_id] = contribution
        #res.append({row.player_id: contribution})
    return res


#def player_contribution(player_data_for: PlayerRow, player_data_against: PlayerRow):



if __name__ == "__main__":
    from hockey.predict.skillset import load_skillset
    conn = open_connection()

    LEAGUE = 13
    SEASON = "20262027"
    # Ids and names both work; the last one is a deliberate miss, so the
    # # "not in the table" footnote is visible in the demo output.
    # PLAYERS = [24417, 6970, "Tom Hedberg", "Zach Wytinck", "Jonathan Wikström",
    #            "Carl Wäng", "Linus Skager", "Nobody Atall"]

    PLAYERS = get_roster(323, SEASON)
    PLAYER_IDS = [k.player_id for k in PLAYERS]
    rows, missing = load_skillset(conn, PLAYER_IDS, 13, 20262027, "skating")
    for row in rows:
        print(f"{row.name:<24}{row.minutes:8.1f}{row.score:8.2f}")
              #f"{pdp:8.2f}{row.score:9.3f}{portal:8.3f}{row.score - portal:8.3f}")
    import time
    started = time.perf_counter()
    player_woi_data = player_woi_data(COLUMNS_FOR, PLAYER_IDS, LEAGUE, SEASON, min_toi=20.0)
    #w_contrib = weighted_contribution(player_woi_data, weights=weights_for)
    rows, missing = load_skillset(conn, PLAYER_IDS, 13, 20262027, "skating")


    # for p in [p for p in PLAYERS if p.player_id in list(w_contrib.keys())]:
    #     print(f"{' '.join([p.first_name, p.last_name]):<30}  {round(w_contrib[p.player_id], 2)}")

    #print(player_woi_data)