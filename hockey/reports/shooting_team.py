#!/usr/bin/python
'''
Output: A pdf report with one TEAM on each line and the same shooting columns
shooting_player_woi.py gives a player. Only events during even strength are
counted.
Input: a league and a season (optionally a list of teams).

Same :data:`COLUMNS` as shooting_player_woi, deliberately: FOR and AGAINST
mean the same thing for a team as for a player -- its own events and the
opponent's -- so the declaration is shared rather than copied, and the two
reports cannot drift apart on what "shots on goal" means.

TWO THINGS READ DIFFERENTLY FROM THE PLAYER VERSION.

TOI IS GAME TIME, NOT ICE TIME. A team is on the ice for every event of its
own games, so a game counts once rather than once per skater: ~51 of 60
minutes per game at even strength. A team's per-60 is therefore about a fifth
of the same lane summed over its players, and the two reports' numbers are not
comparable line for line.

THERE IS NO on-ice ATTRIBUTION AND NO min_toi WORTH SETTING. Nothing is
credited by shift containment here, so no team is dropped for want of ice
time; the floor exists only to keep a club that played two games out of a
rate table.
'''
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hockey.reports.on_ice import (TEAM_IDENTITY, EVEN_STRENGTH, REGULAR,
                                   open_connection, output_path, team_rows,
                                   to_sheet)
from hockey.reports.shooting_player_woi import COLUMNS, _NOTE
from hockey.reports.sheet import render_pdf

_TEAM_NOTE = (_NOTE + " TOI is GAME time, not ice time: a team is on the ice "
              "for every event of its games, so a per-60 here is per 60 "
              "minutes of hockey rather than per 60 minutes of any skater's "
              "shifts.")


def team_report(league: int, season: str, *,
                teams: Iterable[int] | None = None,
                output: Path | str | None = None,
                context=EVEN_STRENGTH,
                stage: str | None = REGULAR,
                min_toi: float = 0.0,
                conn=None,
                title: str | None = None) -> Path:
    """Write the team shooting report and return the path written.

    The same three steps the player report takes -- compute, lay out, render --
    with :func:`~hockey.metrics.on_ice.team_rows` in place of ``player_rows``
    and :data:`~hockey.reports.on_ice.TEAM_IDENTITY` in place of the player
    columns. ``teams`` is SportLogIQ ids; None is every team in the league.
    """
    opened = conn is None
    conn = conn or open_connection()
    try:
        rows = team_rows(conn, teams, league, season, columns=COLUMNS,
                         context=context, stage=stage, min_toi=min_toi)
    finally:
        if opened:
            conn.close()

    sheet = to_sheet(rows, (), columns=COLUMNS,
                     title=title or "Team shooting — even strength",
                     league=league, season=season, stage=stage,
                     context=context, min_toi=min_toi, note_extra=_TEAM_NOTE,
                     identity=TEAM_IDENTITY, row_noun="teams",
                     denominator="game time",
                     note_lead="the events of a team's own games, its own as "
                               "FOR and its opponents' as AGAINST")
    return render_pdf(sheet, output or output_path("shooting_team", league,
                                                   season, stage))


if __name__ == "__main__":
    import time
    LEAGUE = 17
    SEASON = "20262027"

    started = time.perf_counter()
    path = team_report(LEAGUE, SEASON)
    print(f"{path}  ({time.perf_counter() - started:.1f}s)")
