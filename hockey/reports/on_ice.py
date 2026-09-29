#!/usr/bin/python
"""Turning on-ice metrics into a printable sheet.

The presentation half. :mod:`hockey.metrics.on_ice` computes the numbers and
knows nothing about pages; this turns its rows into a
:class:`hockey.reports.sheet.Sheet` -- a title and rows of formatted STRINGS --
and ``sheet.py`` renders that without knowing what any of them mean.

Formatting sits on this side of the seam because "TOI is minutes but TOI/GP is
mm:ss", and "this column is a rate while that one is a total", are facts about
how a metric reads on paper.

The metric names are re-exported so a report module has one import.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Sequence

from hockey.metrics.on_ice import (AGAINST, BOTH, CREDITED, FOR, Column,
                                   ColumnSet, EVEN_STRENGTH, PlayerRow,
                                   REGULAR, WEIGHTS, lane_counts, team_rows,
                                   open_connection, player_rows, team_labels)


#from hockey.metrics.on_ice import (AGAINST, BOTH, FOR, ColumnSet, EVEN_STRENGTH, PlayerRow,
#                                   team_labels)

# --- Handing the numbers to a page -----------------------------------------
# This module does not draw. It turns its own result into a
# hockey.reports.sheet.Sheet -- a title and rows of formatted strings -- and
# the drawing is that module's business. The formatting lives on THIS side of
# the seam on purpose: that TOI is minutes but TOI/GP is mm:ss, and that some
# columns are rates while others are totals, are facts about the metric, not
# about the page.

#: The columns every on-ice report carries before its metrics: who, and how
#: much sample is behind the rates. Widths are in inches -- a player name needs
#: about two, a position needs a third of one -- and the metric columns that
#: follow share whatever is left.
#: (heading, width, alignment, cell) for the columns that are not metrics.
#: The cell is a function of the row, so a team sheet can drop Pos and widen
#: the name without the metric half knowing anything changed.
PLAYER_IDENTITY: tuple[tuple[str, float, str, object], ...] = (
    ("Player", 1.95, "left",  lambda row, teams: row.name),
    ("Team",   0.70, "left",  lambda row, teams: teams.get(row.team_id,
                                                           str(row.team_id or ""))),
    ("Pos",    0.36, "left",  lambda row, teams: row.position),
    ("GP",     0.36, "right", lambda row, teams: str(row.games_played)),
    ("TOI",    0.66, "right", lambda row, teams: f"{row.minutes:.1f}"),
    ("TOI/GP", 0.62, "right", lambda row, teams: _mmss(row.toi_per_game)),
)

#: A team row needs no position, and its name IS the club, so the separate
#: Team column would repeat it. TOI here is game time, not ice time.
TEAM_IDENTITY: tuple[tuple[str, float, str, object], ...] = (
    ("Team",   2.20, "left",  lambda row, teams: row.name),
    ("GP",     0.40, "right", lambda row, teams: str(row.games_played)),
    ("TOI",    0.70, "right", lambda row, teams: f"{row.minutes:.1f}"),
    ("TOI/GP", 0.65, "right", lambda row, teams: _mmss(row.toi_per_game)),
)

#: A side is a meaning; the tone is how a page should say it. For and against
#: are poles, so they take the ends of a diverging pair and the undivided
#: total takes its neutral midpoint. Which hexes those are is the page's
#: business, not this module's.
_TONES = {FOR: "cool", AGAINST: "warm", BOTH: "neutral"}


def _mmss(minutes: float) -> str:
    seconds = int(round(minutes * 60))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _units_phrase(columns: ColumnSet, denominator: str = "ice time") -> str:
    """How to describe the mixture of totals and rates in the subtitle."""
    totals = [column.heading for column in columns if not column.rate]
    rates = [column for column in columns if column.rate]
    if not totals:
        return f"rates per 60 minutes of {denominator} in that situation"
    if not rates:
        return "season totals"
    return (f"{', '.join(dict.fromkeys(totals))} are season totals, the rest "
            f"are per 60 minutes of {denominator} in that situation")


def _bands(columns: ColumnSet, offset: int) -> tuple:
    """One band per run of columns sharing a side, in column order.

    Read off the columns rather than hardcoded, so re-ordering or adding one
    moves the band with it instead of leaving it behind. Offset by the
    identity fields, which sit to their left and belong to no side.
    """
    from hockey.reports.sheet import Band
    out: list[Band] = []
    listed = list(columns)
    for index, column in enumerate(listed):
        if out and listed[index - 1].side == column.side:
            previous = out[-1]
            out[-1] = Band(previous.label, previous.start, previous.span + 1,
                           previous.tone)
        else:
            out.append(Band(column.side.capitalize(), offset + index, 1,
                            _TONES[column.side]))
    return tuple(out)


def to_sheet(rows: Sequence[PlayerRow], missing: Sequence[str] = (), *,
             columns: ColumnSet, title: str,
             league: int | None = None, season: str | None = None,
             stage: str | None = None, context=EVEN_STRENGTH,
             min_toi: float = 0.0, subtitle: Sequence[str] | None = None,
             note: str | None = None, note_extra: str = "",
             identity=PLAYER_IDENTITY, row_noun: str = "players",
             denominator: str = "ice time",
             note_lead: str = "events that happened while the player was on "
                              "the ice"):
    """The computed rows as a :class:`~hockey.reports.sheet.Sheet`.

    Every cell comes out a string, so the page never has to know what a number
    means. ``subtitle`` and ``note`` override the generated ones; ``note_extra``
    adds a sentence to the generated note, which is the usual thing a report
    wants.

    The arguments after ``title`` are there only to be quoted back in the
    header -- they say what was asked for, and nothing here re-derives a number
    from them.
    """
    from hockey.reports.sheet import Field, Sheet

    teams = team_labels()
    if subtitle is None:
        where = " · ".join(str(p) for p in (
            f"League {league}" if league is not None else None,
            f"season {season}" if season else None,
            stage) if p)
        subtitle = tuple(line for line in (
            where,
            "Situation: " + " · ".join(context.describe()),
            f"{len(rows)} {row_noun} · {_units_phrase(columns, denominator)}"
            + (f" · at least {min_toi:g} min" if min_toi else ""),
        ) if line)
    if note is None:
        note = (f"Every column counts {note_lead}, from the metric catalog: "
                + "; ".join(dict.fromkeys(column.describe() for column in columns))
                + ". " + (note_extra + " " if note_extra else "")
                + "TOI is in minutes, TOI/GP as mm:ss. "
                f"Generated {date.today():%Y-%m-%d}.")

    fields = tuple(Field(heading, width, align)
                   for heading, width, align, _ in identity)
    fields += tuple(Field(column.heading) for column in columns)

    table = tuple(
        tuple(cell(row, teams) for _, _, _, cell in identity)
        + tuple(row.cell(column) for column in columns)
        for row in rows
    )

    return Sheet(title=title, fields=fields, rows=table,
                 subtitle=tuple(subtitle), note=note,
                 bands=_bands(columns, len(identity)),
                 footnote_heading="Not in the table",
                 footnotes=tuple(missing))


def output_path(slug: str, league: int, season: str,
                stage: str | None = None) -> Path:
    """Where a report lands when the caller names no file.

    OUTPUT_DIR if it is set, else ./output -- the same convention the rest of
    the repo uses.
    """
    directory = Path(os.getenv("OUTPUT_DIR", "./output")).expanduser()
    stem = f"{slug}_{league}_{season}" + (f"_{stage}" if stage else "")
    return directory / f"{stem}.pdf"
