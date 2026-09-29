#!/usr/bin/python
"""Paginated table sheets, as PDF. Knows nothing about hockey.

The rendering half of ``hockey/reports/``. It takes a :class:`Sheet` -- a
title, some column headings, and rows of ALREADY FORMATTED strings -- and puts
it on A4 landscape pages. It never asks what a number means, how it was
computed or where it came from, which is what lets the metric side be tested
and read without a plotting library in sight.

The seam is deliberately strings. A renderer that took domain objects would
have to know that a TOI is minutes but a TOI/GP is mm:ss, and that some
columns are rates and others totals -- decisions that belong with the metric,
not with the page. So the caller formats, and this module lays out.

WHAT IT DOES DECIDE, because they are layout and nothing else:

* Widths. A :class:`Field` may state one in inches, or leave it None to share
  what is left over. Flexible fields are clamped to a readable band, so a
  five-column sheet does not stretch across A4 and a twenty-column one steps
  its font down instead of becoming unreadable. Below the band the table is
  narrower than the page, and the rules stop at the table rather than the
  margin.
* Pagination. The first page carries the title block and so fits fewer rows
  than the ones after it; a trailing footnote block is given a page of its own
  rather than printed off the sheet.
* The palette. Light only -- this is print. :class:`Band` names a TONE rather
  than a colour ('cool', 'warm', 'neutral'), so a caller says what a run of
  columns MEANS and the mapping to the diverging pair stays here. A band's
  label is drawn in words, so the tint is a second channel and never the only
  one.

Run ``python -m hockey.reports.sheet`` for a worked example on invented data,
which is also the quickest way to see a layout change without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# --- The page description --------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One column of the table.

    ``width`` is in inches; None means "share whatever the fixed columns leave",
    which is what every metric column wants. ``align`` is 'left' or 'right'.
    """
    heading: str
    width: float | None = None
    align: str = "right"


@dataclass(frozen=True)
class Band:
    """A labelled, tinted run of fields drawn above their headings.

    ``start`` indexes :attr:`Sheet.fields`. ``tone`` is 'cool', 'warm' or
    'neutral' -- what the run means, not what colour it is.
    """
    label: str
    start: int
    span: int
    tone: str = "neutral"


@dataclass(frozen=True)
class Sheet:
    """Everything one PDF needs, with every cell already a string."""
    title: str
    fields: tuple[Field, ...]
    rows: tuple[tuple[str, ...], ...]
    subtitle: tuple[str, ...] = ()
    note: str = ""
    bands: tuple[Band, ...] = ()
    footnote_heading: str = ""
    footnotes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        width = len(self.fields)
        for index, row in enumerate(self.rows):
            if len(row) != width:
                raise ValueError(
                    f"row {index} has {len(row)} cells against {width} fields; "
                    f"a Sheet's rows must line up with its headings")
        for band in self.bands:
            if band.start < 0 or band.start + band.span > width:
                raise ValueError(
                    f"band {band.label!r} covers fields "
                    f"{band.start}..{band.start + band.span - 1} of {width}")


# --- Ink and tint ----------------------------------------------------------
# A print surface, so the light palette only. The tones are the diverging pair
# plus its neutral midpoint, laid on at low alpha so every cell keeps
# near-black text on near-white.

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_RULE = "#c3c2b7"
_ZEBRA = "#f2f1ed"
_TONES = {
    "neutral": ("#8d8c86", 0.18),   # the diverging midpoint
    "cool":    ("#2a78d6", 0.13),   # cool pole
    "warm":    ("#d03b3b", 0.13),   # warm pole
}

# Page geometry, in inches measured down from the top-left corner.
_PAGE = (11.69, 8.27)       # A4 landscape
_MARGIN = 0.5
_ROW_HEIGHT = 0.235
_BAND_ROW = 0.24
_NAME_ROW = 0.26
_TABLE_HEAD = _BAND_ROW + _NAME_ROW
_FOOTER_HEIGHT = 0.5
_CONT_TOP = 0.62

#: A flexible column is sized to fill the page, but only within reason: a
#: five-column sheet stretched across A4 reads as a scatter of numbers, and a
#: twenty-column one would be unreadably narrow.
_FLEX_MAX = 0.92
_FLEX_MIN = 0.40


# --- Layout ----------------------------------------------------------------

def _flex_width(sheet: Sheet) -> float:
    fixed = sum(f.width for f in sheet.fields if f.width is not None)
    flexible = sum(1 for f in sheet.fields if f.width is None)
    if not flexible:
        return 0.0
    available = _PAGE[0] - 2 * _MARGIN - fixed
    return min(max(available / flexible, _FLEX_MIN), _FLEX_MAX)


def _positions(sheet: Sheet) -> list[tuple[float, float, str]]:
    """(left, width, align) per field, left to right."""
    flex = _flex_width(sheet)
    out: list[tuple[float, float, str]] = []
    x = _MARGIN
    for f in sheet.fields:
        width = flex if f.width is None else f.width
        out.append((x, width, f.align))
        x += width
    return out


def _table_right(sheet: Sheet) -> float:
    """The table's right edge, which is the page's only when it fills it."""
    left, width, _ = _positions(sheet)[-1]
    return left + width


def _cell_size(sheet: Sheet) -> float:
    flex = _flex_width(sheet)
    return 7.6 if not flex or flex >= 0.50 else 6.8


def _title_bottom(subtitle: Sequence[str]) -> float:
    return 0.95 + 0.19 * len(subtitle) + 0.18


# --- Drawing ---------------------------------------------------------------

def _cell(ax, text: str, left: float, width: float, y: float, align: str,
          *, weight: str = "normal", size: float = 7.6, color: str = _INK) -> None:
    pad = 0.06
    if align == "right":
        ax.text(left + width - pad, y, text, ha="right", va="center",
                fontsize=size, color=color, fontweight=weight)
    else:
        ax.text(left + pad, y, text, ha="left", va="center",
                fontsize=size, color=color, fontweight=weight)


def _page_axes(figure):
    """One axes covering the sheet, in inches down from the top-left.

    Every coordinate above is then a position on the page rather than a
    fraction of something, which is what makes the widths readable as a layout.
    """
    ax = figure.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, _PAGE[0])
    ax.set_ylim(_PAGE[1], 0)
    ax.axis("off")
    ax.set_facecolor(_SURFACE)
    return ax


def _draw_title(ax, title: str, subtitle: Sequence[str], right: float) -> float:
    from matplotlib.lines import Line2D
    ax.text(_MARGIN, 0.60, title, ha="left", va="center", fontsize=17,
            fontweight="bold", color=_INK)
    y = 0.95
    for line in subtitle:
        ax.text(_MARGIN, y, line, ha="left", va="center", fontsize=8.2,
                color=_INK_SECONDARY)
        y += 0.19
    ax.add_line(Line2D([_MARGIN, right], [y - 0.05, y - 0.05],
                       color=_RULE, linewidth=0.8))
    return _title_bottom(subtitle)


def _draw_header(ax, sheet: Sheet, top: float,
                 positions: Sequence[tuple[float, float, str]]) -> float:
    """Band row, then headings. Returns the bottom of the header."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    size = _cell_size(sheet)
    for band in sheet.bands:
        tint, alpha = _TONES.get(band.tone, _TONES["neutral"])
        left = positions[band.start][0]
        last_left, last_width, _ = positions[band.start + band.span - 1]
        width = last_left + last_width - left
        ax.add_patch(Rectangle((left, top), width, _TABLE_HEAD, facecolor=tint,
                               alpha=alpha, edgecolor="none", zorder=0))
        ax.text(left + width / 2, top + _BAND_ROW / 2, band.label, ha="center",
                va="center", fontsize=8, fontweight="bold", color=_INK_SECONDARY)

    y = top + _BAND_ROW + _NAME_ROW / 2
    for (left, width, align), f in zip(positions, sheet.fields):
        _cell(ax, f.heading, left, width, y, align, weight="bold",
              size=min(size, 7.4))

    bottom = top + _TABLE_HEAD
    ax.add_line(Line2D([_MARGIN, _table_right(sheet)], [bottom, bottom],
                       color=_RULE, linewidth=0.8))
    return bottom


def _draw_rows(ax, sheet: Sheet, rows: Sequence[Sequence[str]], top: float,
               positions: Sequence[tuple[float, float, str]]) -> float:
    from matplotlib.patches import Rectangle
    size = _cell_size(sheet)
    right = _table_right(sheet)
    y = top
    for index, row in enumerate(rows):
        if index % 2:
            ax.add_patch(Rectangle((_MARGIN, y), right - _MARGIN, _ROW_HEIGHT,
                                   facecolor=_ZEBRA, edgecolor="none", zorder=0))
        middle = y + _ROW_HEIGHT / 2
        for (left, width, align), text in zip(positions, row):
            _cell(ax, text, left, width, middle, align, size=size)
        y += _ROW_HEIGHT
    return y


def _draw_footer(ax, page: int, pages: int, note: str) -> None:
    import textwrap
    lines = textwrap.wrap(note, 138) or [""]
    y = _PAGE[1] - _MARGIN + 0.16 - 0.13 * (len(lines) - 1)
    for index, line in enumerate(lines):
        ax.text(_MARGIN, y + index * 0.13, line, ha="left", va="center",
                fontsize=6.6, color=_INK_MUTED)
    ax.text(_PAGE[0] - _MARGIN, _PAGE[1] - _MARGIN + 0.16, f"{page} / {pages}",
            ha="right", va="center", fontsize=6.8, color=_INK_MUTED)


def _draw_footnotes(ax, y: float, heading: str, notes: Sequence[str]) -> None:
    ax.text(_MARGIN, y + 0.30, heading, ha="left", va="center",
            fontsize=7.6, fontweight="bold", color=_INK_SECONDARY)
    for index, entry in enumerate(notes):
        ax.text(_MARGIN, y + 0.52 + index * 0.17, f"·  {entry}", ha="left",
                va="center", fontsize=7.2, color=_INK_MUTED)


def render_pdf(sheet: Sheet, output: Path | str) -> Path:
    """Write ``sheet`` to ``output`` as a paginated PDF and return the path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    positions = _positions(sheet)
    right = _table_right(sheet)
    usable = _PAGE[1] - _MARGIN - _FOOTER_HEIGHT
    first_rows = max(int((usable - _title_bottom(sheet.subtitle) - _TABLE_HEAD)
                         // _ROW_HEIGHT), 1)
    later_rows = max(int((usable - _CONT_TOP - _TABLE_HEAD) // _ROW_HEIGHT), 1)

    pages: list[Sequence[Sequence[str]]] = []
    remaining = list(sheet.rows)
    while remaining or not pages:
        take = first_rows if not pages else later_rows
        pages.append(remaining[:take])
        remaining = remaining[take:]
    if sheet.footnotes:
        # The footnotes need room of their own; a page ending flush with its
        # last row would print them off the sheet.
        top = _title_bottom(sheet.subtitle) if len(pages) == 1 else _CONT_TOP
        used = top + _TABLE_HEAD + _ROW_HEIGHT * len(pages[-1])
        if used + 0.35 + 0.17 * len(sheet.footnotes) > usable:
            pages.append([])

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output) as pdf:
        for index, page_rows in enumerate(pages):
            figure = plt.figure(figsize=_PAGE, facecolor=_SURFACE)
            ax = _page_axes(figure)
            if index == 0:
                top = _draw_title(ax, sheet.title, sheet.subtitle, right)
            else:
                ax.text(_MARGIN, 0.34, f"{sheet.title} (continued)", ha="left",
                        va="center", fontsize=9, color=_INK_SECONDARY)
                top = _CONT_TOP
            header_bottom = _draw_header(ax, sheet, top, positions)
            bottom = _draw_rows(ax, sheet, page_rows, header_bottom, positions)
            if sheet.footnotes and index == len(pages) - 1:
                _draw_footnotes(ax, bottom, sheet.footnote_heading,
                                sheet.footnotes)
            _draw_footer(ax, index + 1, len(pages), sheet.note)
            pdf.savefig(figure, facecolor=_SURFACE)
            plt.close(figure)
    return output