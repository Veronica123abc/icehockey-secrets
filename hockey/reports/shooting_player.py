#!/usr/bin/python
'''
Output: A pdf report with one player on each line and the same shooting
columns shooting_player_woi.py gives him, counted from HIS OWN shots rather
than from every shot taken while he was on the ice. Only events during even
strength are counted.
Input: a list of players, a league and a season.

The third of the three attributions the metric layer offers, and the narrowest:

    shooting_player_woi   every event while he was on the ice, FOR and AGAINST
    shooting_team         every event of his team's games, FOR and AGAINST
    shooting_player       the events he is named in                 (this one)

Same lanes as the other two, deliberately -- "shots on goal" has to mean the
same thing whoever it is attributed to -- so only the side changes, from FOR
to :data:`~hockey.metrics.on_ice.CREDITED`.

THERE IS NO "AGAINST" HERE, and asking for one is an error rather than an
empty column: an event names one shooter, and the opponent's shots are not
something a player does. A column that reads "shots against Norbe" is a
question about who was on the ice, which is the woi report.

THE DENOMINATOR IS STILL HIS OWN EVEN-STRENGTH ICE TIME, so the rates are
directly comparable with the FOR half of the woi report -- and are about a
fifth of them, because the woi column counts his four team-mates' shots too.
The ratio between the two is the player's share of the shooting done while he
is out there: over MoDo's 2025/26 skaters it averages 20% and runs from 7% to
30%, which is a more useful thing to read off the pair than either alone.

CREDIT DOES NOT NEED THE SHIFT TO CONTAIN THE MOMENT. An event naming him as
the actor is better evidence than a shift interval that disagrees with it, and
about 2% of events sit just outside the shift that should contain them. That
rule is made in ``_credit`` in ``hockey/metrics/on_ice.py`` and applies to the
CREDITED side only; the woi side uses strict containment, which is what
reconciles it with the supplier's published totals.

IT DOES NEED HIM TO HAVE A LINE FOR THAT GAME. A player with no second of the
selected situation in a game is not playing it by this report's definition, so
an event of his there has nowhere to go. Summed over every player in league 17
2025/26 against the same lanes counted by team: all 1403 even-strength goals
are credited, and 31,143 of 31,149 shot attempts. The six are six different
players in six different games, each with no even-strength shift in the game he
shot in.

CHECKED AGAINST THE SUPPLIER, not only against ourselves --
``hockey/regression/supplier.py`` compares every one of these columns to the
numbers they publish, for every skater in the league season. Shots taken match
exactly for 420 of 429 players and within one for 428; goals for 427 of 429 and
within one for all of them. The one player beyond that, Alfred Hjalm, has
shifts in 11 of the 20 games he dressed for, which is an ingestion gap rather
than a disagreement about the metric.

xG SUMS THE PUBLISHED VALUE, NOT THE RAW ONE -- ``weight="xg_official"``. The
supplier raises every ungraded slot shot to a grade C chance downstream of the
event feed, so summing the feed's own number lands 2.2% low: 1,487.5 against
their 1,521.1 over the league season, 1,519.4 with the adjustment. See
:func:`~hockey.metrics.on_ice._xg_official`.
'''
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hockey.reports.on_ice import (CREDITED, Column, ColumnSet, EVEN_STRENGTH,
                                   REGULAR, open_connection, output_path,
                                   player_rows, to_sheet)
from hockey.reports.sheet import render_pdf

#: The report, in one place -- the FOR half of shooting_player_woi's columns
#: with the side changed. Adding a column means adding a lane key here.
#:
#: For season totals rather than rates, uncomment the two leading columns: an
#: individual goal count is the number people quote, where a rate is the one
#: that compares two players who did not play the same minutes.
COLUMNS = ColumnSet((
    # Column("G (tot)",  "Goals · All", CREDITED, rate=False),
    # Column("SA (tot)", "Shots · All", CREDITED, rate=False),
    Column("G",    "Goals · All",    CREDITED),
    Column("xG",   "Shots · All",    CREDITED, weight="xg_official"),
    Column("SA",   "Shots · All",    CREDITED),
    Column("SOG",  "Shots · On Net", CREDITED),
    Column("Slot", "Shots · Slot",   CREDITED),
))

_NOTE = ("xG is the supplier's expected_goals_all_shots summed over the "
         "player's own shot attempts, with ungraded slot shots raised to a "
         "grade C chance as the supplier's own published figures do; SOG "
         "includes goals; Slot is inner + outer slot. The denominator is his "
         "even-strength ice time, the same one the on-ice report uses, so the "
         "two are comparable.")


def player_report(players: Iterable, league: int, season: str, *,
                  output: Path | str | None = None,
                  context=EVEN_STRENGTH,
                  stage: str | None = REGULAR,
                  min_toi: float = 0.0,
                  conn=None,
                  title: str | None = None) -> Path:
    """Write the individual shooting report and return the path written.

    The same three steps the other two reports take -- compute, lay out,
    render -- with nothing but :data:`COLUMNS` and the naming specific to this
    one. See :func:`hockey.reports.on_ice.player_rows` for the arguments.
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
                     title=title or "Individual shooting — even strength",
                     league=league, season=season, stage=stage,
                     context=context, min_toi=min_toi, note_extra=_NOTE,
                     note_lead="events the player himself is named in, not "
                               "events he was merely on the ice for")
    return render_pdf(sheet, output or output_path("shooting_player", league,
                                                   season, stage))


if __name__ == "__main__":
    import time
    from hockey.reports.helpers.get_roster import get_roster

    LEAGUE = 17
    SEASON = "20252026"
    PLAYERS = get_roster(1395, SEASON)

    started = time.perf_counter()
    path = player_report(PLAYERS, LEAGUE, SEASON, min_toi=20.0)
    print(f"{path}  ({time.perf_counter() - started:.1f}s)")
