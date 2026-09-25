#!/usr/bin/python
"""On-ice metrics: any metric-catalog lanes, per player, over a season.

The game canvas's player report counts, per player, the events of the ticked
metric-catalog lanes that happened while he was on the ice, narrowed by a
context selection, for ONE game. This is that with the game count raised to a
season and the ticking done in Python -- and nothing here knows WHICH lanes, so
a new report is a list of :class:`Column` and a title.

THIS MODULE COMPUTES; IT DOES NOT DRAW. It imports no plotting library and
never opens a file for output. A report is three visible steps::

    from hockey.reports.on_ice import (Column, ColumnSet, FOR,
                                       open_connection, player_rows, to_sheet)
    from hockey.reports.sheet import render_pdf

    COLUMNS = ColumnSet((
        Column("Entries", "Controlled entries · Successful", FOR),
        Column("Dump-ins", "Dump-ins · All", FOR),
    ))
    rows, missing = player_rows(conn, players, 17, "20252026", columns=COLUMNS)
    sheet = to_sheet(rows, missing, columns=COLUMNS, title="Entries")
    render_pdf(sheet, "output/entries.pdf")

:func:`player_rows` is the whole metric side and returns plain data, so it can
be printed, charted, diffed against the canvas or checked in a notebook with
no page in sight. :func:`to_sheet` is the only thing here that knows a page
exists, and even it only builds a description -- a title and rows of formatted
STRINGS -- which ``hockey/reports/sheet.py`` renders without knowing what any
of them mean. Formatting sits on this side because "TOI is minutes but TOI/GP
is mm:ss" is a fact about the metric, not about the paper.

``player_woi.py`` and ``player_entries.py`` are both those three lines plus a
:class:`ColumnSet`, and neither contains a line of fetching or drawing.

NO METRIC IS DEFINED HERE. A column names LANES of
``hockey/derive/metric_catalog.py`` and counts them with those lanes' own
predicates, so "shots on goal" cannot come to mean something different on a
report than on the canvas rail. What this module owns is aggregation: over
which games, in which situation, credited to whom, and divided by what.

A COLUMN IS A SELECTION, NOT ONE PREDICATE, and it follows the filter-group
contract exactly: OR within a group, AND across groups. Lanes carry their own
group, so that falls out of the keys with nothing to declare --
``("Controlled entries · Successful", "Controlled entries · With Play After")``
is Result AND With-Play-After, while ``("Controlled entries · With Shot On
Net", "Controlled entries · With Slot Shot")`` is one group twice and reads as
either. All the lanes of one column must come from the same population, which
is checked at construction rather than discovered in the numbers.

SIDES. :data:`FOR` and :data:`AGAINST` split a column by whose event it was --
the canvas expresses the same thing with its team selector -- and :data:`BOTH`
leaves it undivided. A BOTH column is the one directly comparable to a canvas
number and to a hand count, which is why the WOI report leads with two of them.

WEIGHTS. A lane is a population and a predicate, which is all a COUNT needs. A
weighted total needs a third thing, so a column may name a ``weight`` from
:data:`WEIGHTS` -- expected goals is the only one today. That is an aggregation
choice; the population it aggregates still comes from the catalog.

WHAT IS FETCHED, AND WHY IN THAT ORDER. Building games is the thing to avoid --
~0.9s and ~23MB each. Instead, three bulk queries:

1. ``query_shifts(player_sl_ids=...)`` -- the requested players' own shifts.
   This says WHICH GAMES the report must look at at all (51 of a 410-game
   season for one player) and costs ~0.01s.
2. ``query_shifts(game_sl_ids=those games)`` -- every shift of those games,
   goalies included, because even-strength ice time is swept out of them and a
   pulled goalie is not a penalty.
3. ``query_events(game_sl_ids=those games, names=...)`` -- only the event names
   the columns actually read, derived from their lanes so the query cannot ask
   for less than the report counts.

MEASURED, BECAUSE THE OBVIOUS NARROWING IS THE SLOW ONE. ``query_events`` can
narrow to one player's on-ice time itself, with an interval join against
`shift` (``on_ice_player_sl_id``). It returns the same events, and for one
player over a season it took 24.0s against 2.1s for step 3 over the 65 games he
played -- and that cost is paid per player. Narrowing to the players' GAMES and
attributing on-ice in Python, off shifts this report needs anyway for its
denominator, is the same answer an order of magnitude quicker.

``with_on_ice=True`` is not optional. ``context_filter`` reads the goalie refs
to tell "both goalies on the ice" from "goalie pulled", and only the on-ice
reconstruction fills them in; with it off every event classifies as 'Goalie
out'. It costs ~4s over a whole season, because the shifts it reconstructs
from are the ones already being read.

TWO HALVES, TWO CLASSIFIERS, DELIBERATELY. An event is classified by the
supplier's own fields, as the canvas classifies it, because the supplier wins
wherever it publishes a value. Ice time is not an event and carries no such
fields, so it is swept: every shift of the game is cut at each on/off boundary
and each slice classified from the skater counts
(``hockey/metrics/player/on_ice_spans.py``).

TIED TO THE SUPPLIER'S PUBLISHED NUMBERS. Player 24417, league 17, 2025/26, as
the supplier publishes him: 934 even-strength minutes, 37 on-ice goals for, 914
shot attempts for. This engine reproduces all three (934.5, 37, 914). It did
not at first, and all three discrepancies were SELECTION choices rather than
metrics -- see :data:`EVEN_STRENGTH`, :data:`REGULAR` and :func:`_credit`, each
of which records what it cost. When a number is wrong, check which EVENTS are
being selected before suspecting what is being counted.
"""
from __future__ import annotations

import os
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hockey.derive import context_filter as ctx
from hockey.derive import metric_catalog as catalog
from hockey.model.events import Event
from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval
from hockey.metrics.player.on_ice_spans import SituationTimeline, skater_spans
import time
#: EVEN STRENGTH AS THE SUPPLIER COUNTS IT: even manpower, whatever the
#: goalies are doing. ``ctx.DEFAULT`` is NOT this -- it also demands both
#: goalies on the ice, which is the right default for the game canvas (you are
#: looking at a game, and an empty net is a different thing) and the wrong one
#: for a season total published alongside the supplier's. A pulled goalie buys
#: an extra attacker, not an advantage: 6v5 is even strength and the supplier
#: labels it so. Excluding it cost the reference player 49 of his 934
#: even-strength minutes, 3 of 37 on-ice goals and 67 of 914 shot attempts.
EVEN_STRENGTH = ctx.DEFAULT.with_values(ctx.GOALIES, ctx.GOALIE_SITUATIONS)

#: The stage a season total means unless asked otherwise. The supplier's
#: published season numbers are the regular season; the whole season including
#: playoffs was 20% high on every column.
REGULAR = "regular"

#: Which bench a column counts. The event's own team decides it; BOTH is the
#: undivided on-ice total, which is what the canvas's WOI report shows with its
#: team selector left on "both teams".
FOR, AGAINST, BOTH = "for", "against", "both"


def _xg(event: Event) -> float:
    """The supplier's expected goals for a shot; 0.0 where it published none.

    Typed on Event and populated on every source, but occasionally a string on
    the file path, hence the cast rather than a bare float().
    """
    value = event.expected_goals_all_shots
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


#: Named weights a column may sum instead of counting events.
WEIGHTS = {"xg": _xg}


@dataclass(frozen=True)
class Column:
    """One counted column: catalog lanes, a side, and how to add them up.

    ``lanes`` is one key of :data:`hockey.derive.metric_catalog.BY_KEY`, or
    several -- OR within a filter group, AND across groups, the same contract
    every metric module documents. The predicates behind a column are the
    metric layer's, never this file's.

    ``weight`` is None for a plain count, or a key of :data:`WEIGHTS` for a
    weighted total. ``rate`` is what the page prints: True divides by ice time,
    False prints the total itself -- a rate is the comparable number between
    players, a total is the checkable one.
    """
    heading: str
    lanes: tuple[str, ...] | str
    side: str = FOR
    weight: str | None = None
    rate: bool = True

    def __post_init__(self) -> None:
        lanes = ((self.lanes,) if isinstance(self.lanes, str)
                 else tuple(self.lanes))
        if not lanes:
            raise ValueError(f"column {self.heading!r} names no lane")
        unknown = [key for key in lanes if key not in catalog.BY_KEY]
        if unknown:
            raise KeyError(
                f"column {self.heading!r} names unknown lane(s) {unknown}; "
                f"run `python -m hockey.derive.metric_catalog` for the tree")
        populations = {catalog.BY_KEY[key].population for key in lanes}
        if len(populations) > 1:
            # ANDing lanes from two populations can never match: an event has
            # one name. Caught here rather than as a silently empty column.
            raise ValueError(
                f"column {self.heading!r} mixes populations {sorted(populations)}; "
                f"the lanes of one column must describe one population")
        if self.side not in (FOR, AGAINST, BOTH):
            raise ValueError(f"column {self.heading!r} has side {self.side!r}")
        if self.weight is not None and self.weight not in WEIGHTS:
            raise KeyError(f"column {self.heading!r} names unknown weight "
                           f"{self.weight!r}; known: {sorted(WEIGHTS)}")
        object.__setattr__(self, "lanes", lanes)

    @property
    def key(self) -> str:
        return f"{'+'.join(self.lanes)}|{self.side}|{self.weight or 'count'}"

    @property
    def event_name(self) -> str:
        return catalog.BY_KEY[self.lanes[0]].event_name

    def describe(self) -> str:
        """The selection in words, for the page footer."""
        by_group: dict[str, list[str]] = {}
        for key in self.lanes:
            lane = catalog.BY_KEY[key]
            by_group.setdefault(lane.group or "", []).append(lane.item)
        population = catalog.BY_KEY[self.lanes[0]].population
        parts = [" or ".join(items) for items in by_group.values()]
        return f"{population} ({' and '.join(parts)})"


class ColumnSet:
    """The columns of one report, with what has to be derived from them.

    Three things are needed alongside the list itself and all three fall out of
    the lanes, so none of them is declared twice: which supplier event names to
    query, and -- per column -- which lanes must EACH contribute a match (the
    AND) and which are alternatives (the OR).
    """

    __slots__ = ("columns", "event_names", "_tests")

    def __init__(self, columns: Iterable[Column]) -> None:
        self.columns: tuple[Column, ...] = tuple(columns)
        if not self.columns:
            raise ValueError("a report needs at least one column")
        self.event_names: tuple[str, ...] = tuple(dict.fromkeys(
            column.event_name for column in self.columns))
        # column -> one tuple of alternative lane keys per filter group. A
        # column hits when every tuple contributes at least one match.
        self._tests: list[tuple[Column, tuple[tuple[str, ...], ...]]] = []
        for column in self.columns:
            by_group: dict[str, list[str]] = {}
            for key in column.lanes:
                by_group.setdefault(catalog.BY_KEY[key].group or "", []).append(key)
            self._tests.append(
                (column, tuple(tuple(keys) for keys in by_group.values())))

    def __iter__(self):
        return iter(self.columns)

    def __len__(self) -> int:
        return len(self.columns)

    def hits(self, matched: set[str]) -> list[Column]:
        """The columns whose selection the matched lane keys satisfy."""
        return [column for column, groups in self._tests
                if all(any(key in matched for key in group) for group in groups)]


@dataclass
class PlayerRow:
    """One player's line: the sample, then one total per column."""
    player_id: int
    name: str
    position: str
    team_id: int | None
    games_played: int = 0
    toi: float = 0.0                    # seconds in the selected situation
    totals: dict[str, float] = field(default_factory=dict)

    @property
    def minutes(self) -> float:
        return self.toi / 60.0

    @property
    def toi_per_game(self) -> float:
        return self.minutes / self.games_played if self.games_played else 0.0

    def per60(self, column: Column) -> float:
        """A column as a rate per 60 minutes of ice time.

        Derived, never stored: the total and the ice time are both on the row
        already. The denominator is THIS row's TOI, which is the situation's
        ice time and not the whole game's -- even-strength events over
        even-strength minutes, which is the only way the rate means anything.
        """
        hours = self.toi / 3600.0
        return self.totals.get(column.key, 0.0) / hours if hours else 0.0

    def cell(self, column: Column) -> str:
        """What the page prints for one column: a rate, or a raw total."""
        if column.rate:
            return f"{self.per60(column):.2f}"
        total = self.totals.get(column.key, 0.0)
        return f"{total:.0f}" if column.weight is None else f"{total:.1f}"


# --- Gathering -------------------------------------------------------------

def open_connection():
    """A database connection.

    ``open_database_azure`` loads the .env itself, so this needs no ceremony
    of its own -- it used to carry a private copy of that loading, which was
    a third spelling of something that belongs next to the variables it
    reads.
    """
    from hockey.db.database import open_database_azure
    return open_database_azure()


def _resolve_players(conn, players: Iterable, league: int,
                     season: str) -> tuple[list[int], list[str]]:
    """Requested players -> (SportLogIQ ids, requests nothing answered).

    A request is an id, a name, or anything carrying a ``player_id``. Names are
    matched case-insensitively against the players who appear in this league
    and season, full name first and surname as a fallback when exactly one
    player answers to it -- two Anderssons ask for the full name rather than
    having one picked for them.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT DISTINCT p.sl_id, p.first_name, p.last_name
               FROM affiliation a
               JOIN player p ON p.id = a.player_id
               JOIN game g ON g.id = a.game_id
               WHERE g.league_id = (SELECT id FROM league WHERE sl_id = %s)
                 AND g.season = %s""",
            (int(league), str(season)))
        rows = cursor.fetchall()
    finally:
        cursor.close()

    known: set[int] = set()
    by_name: dict[str, list[int]] = {}
    for player_sl, first, last in rows:
        known.add(int(player_sl))
        full = " ".join(p for p in ((first or "").strip(), (last or "").strip()) if p)
        if not full:
            continue
        by_name.setdefault(full.casefold(), []).append(int(player_sl))
        surname = full.rsplit(" ", 1)[-1].casefold()
        if surname != full.casefold():
            by_name.setdefault(surname, []).append(int(player_sl))

    wanted: list[int] = []
    missing: list[str] = []
    for request in players:
        value = getattr(request, "player_id", request)
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            player_id = int(value)
            if player_id in known:
                wanted.append(player_id)
            else:
                missing.append(f"{player_id} — did not play in this league and season")
            continue
        candidates = by_name.get(" ".join(str(value).split()).casefold(), [])
        if len(candidates) == 1:
            wanted.append(candidates[0])
        elif candidates:
            missing.append(f"{value} — matches {len(candidates)} players; "
                           f"ask by id ({', '.join(str(c) for c in candidates)})")
        else:
            missing.append(f"{value} — no player of that name in this league and season")
    return list(dict.fromkeys(wanted)), missing


def _by_game(intervals: Iterable[ToIInterval]) -> dict[int, list[ToIInterval]]:
    out: dict[int, list[ToIInterval]] = defaultdict(list)
    for interval in intervals:
        out[interval.game_id].append(interval)
    return out


def player_rows(conn, players: Iterable, league: int, season: str, *,
                columns: ColumnSet,
                context=EVEN_STRENGTH, stage: str | None = REGULAR,
                min_toi: float = 0.0) -> tuple[list[PlayerRow], list[str]]:
    """The report's numbers: ``(rows, unanswered requests)``.

    Split from the PDF so the same figures can be printed, charted, or checked
    against the canvas without rendering anything. See the module docstring for
    what is counted and how it is fetched.
    """
    from hockey.db.event_query import query_events
    from hockey.db.roster_query import query_rosters
    from hockey.db.shift_query import query_shifts

    wanted, missing = _resolve_players(conn, players, league, season)
    if not wanted:
        return [], missing

    # 1. The requested players' own shifts: which games matter, and which team
    #    each played for in each of them.
    own_shifts = query_shifts(conn, league_sl_id=league, season=season,
                              player_sl_ids=wanted, include_goalies=False)
    if stage:
        own_shifts = _narrow_to_stage(conn, own_shifts, league, season, stage)
    game_ids = sorted({shift.game_id for shift in own_shifts})
    if not game_ids:
        return [], missing + [f"{len(wanted)} player(s) have no shifts in this season"]

    # 2. Every shift of those games -- goalies included, because the sweep that
    #    classifies ice time has to tell a pulled goalie from a penalty.
    shifts_by_game = _by_game(query_shifts(conn, game_sl_ids=game_ids))
    rosters = query_rosters(conn, game_sl_ids=game_ids)

    # 3. The events those columns read, and no others. with_on_ice because the
    #    context filter reads the goalie refs -- see the module docstring.
    events_by_game = defaultdict(list)
    for event in query_events(conn, game_sl_ids=game_ids,
                              names=list(columns.event_names), with_on_ice=True):
        events_by_game[event.game_id].append(event)

    empty_roster = Roster(game_id=0, players={})
    rows: dict[int, PlayerRow] = {}
    wanted_set = set(wanted)

    for game_id in game_ids:
        roster = rosters.get(game_id, empty_roster)
        toi = shifts_by_game.get(game_id, [])
        if not toi:
            continue
        spans = skater_spans(toi, roster)
        timeline = SituationTimeline(toi, roster)

        # -- the denominator: ice time in the selected situation
        playing: dict[int, int] = {}
        for player_id in wanted_set & set(spans):
            player = roster.players.get(player_id)
            team_id = player.team_id if player is not None else None
            seconds = timeline.selected_seconds(spans[player_id], team_id, context)
            if seconds <= 0:
                # On the ice, but never in the selected situation: not a game
                # played, by this report's definition of played.
                continue
            playing[player_id] = team_id
            row = rows.get(player_id)
            if row is None:
                name, position = _identity(roster, player_id)
                row = rows[player_id] = PlayerRow(
                    player_id=player_id, name=name, position=position,
                    team_id=team_id,
                    totals=dict.fromkeys((c.key for c in columns), 0.0))
            row.games_played += 1
            row.toi += seconds
            row.team_id = team_id

        if not playing:
            continue

        # -- the numerators: every selected event, credited to the players of
        #    this report who were on the ice for it.
        _credit(events_by_game.get(game_id, []), spans, playing, rows, context,
                columns)

    out = [row for row in rows.values() if row.minutes > min_toi]
    out.sort(key=lambda row: row.toi, reverse=True)

    reported = {row.player_id for row in out}
    for player_id in wanted:
        if player_id not in reported:
            missing.append(f"{player_id} — no ice time in the selected situation"
                           + (f" above {min_toi:g} min" if min_toi else "")
                           + " in this season")
    return out, missing


def _identity(roster: Roster, player_id: int) -> tuple[str, str]:
    player = roster.players.get(player_id)
    if player is None:
        return str(player_id), ""
    first = (player.first_name or "").strip()
    last = (player.last_name or "").strip()
    return (" ".join(p for p in (first, last) if p) or str(player_id),
            player.position or "")


def _credit(events: Sequence[Event], spans: dict[int, list[tuple[float, float]]],
            playing: dict[int, int | None], rows: dict[int, PlayerRow],
            context, columns: ColumnSet) -> None:
    """Add one game's events to the rows of the players on the ice for them.

    The lane predicates are evaluated ONCE per event, not once per player: a
    season's shots against a dozen players would otherwise run the same
    predicate a dozen times for the same answer.

    The event's own classification decides whether it is in the selected
    situation, which is what the canvas does; at even strength the answer is
    the same from either bench anyway, and where it is not -- a power play --
    the supplier's value is the one that wins.

    ON THE ICE MEANS THE SHIFT CONTAINS THE MOMENT, strictly. ``skater.py``
    also credits an event to its OWN player when the shift data puts it just
    outside the shift it credits -- about 2% of events sit there -- so that a
    player's own goal can never be missing from his WOI. That rule is right for
    the question skater.py asks (is WOI a superset of what he is credited
    with?) and wrong for this one: the supplier's published totals use strict
    containment, and the rule added 10 shot attempts and one goal to the
    reference player's season. Checked rather than argued -- see the module
    docstring for the numbers it reconciles.
    """

    for event in events:
        # Asked once per event, not once per credited player: the inner loop
        # below is the P x E term, and a call in it is paid a few million
        # times over a season.
        event_team = ctx.team_of(event)
        if event.t is None or event_team is None:
            continue
        if not context.matches(event):
            continue
        lanes = catalog.BY_EVENT.get(event.name)
        if not lanes:
            continue
        matched = {lane.key for lane in lanes if lane.matches(event)}
        if not matched:
            continue
        hits = columns.hits(matched)
        if not hits:
            continue

        for player_id, team_id in playing.items():
            player_spans = spans.get(player_id)
            if not player_spans:
                continue
            index = bisect_right(player_spans, (event.t, float("inf")))
            if not (index > 0 and player_spans[index - 1][0] <= event.t
                    < player_spans[index - 1][1]):
                continue
            side = FOR if team_id == event_team else AGAINST
            totals = rows[player_id].totals
            for column in hits:
                if column.side not in (side, BOTH):
                    continue
                weight = WEIGHTS[column.weight](event) if column.weight else 1.0
                totals[column.key] += weight


def _narrow_to_stage(conn, shifts, league: int, season: str, stage: str):
    """Drop shifts from games outside one stage ('regular' / 'playoffs').

    A NULL `stage` counts as regular season. That is an ingestion gap, not a
    third kind of game: league 17's 2025/26 has two of them, 186449 and 186461,
    and the schedule manifest gives both as 'regular'. Leaving them out put the
    reference player 16 even-strength minutes and 10 shot attempts short of the
    supplier's published season.

    Resolved against the database rather than the manifest on purpose -- these
    reports have to work in a db_only deployment, where DATA_ROOT_DIR is unset
    and there is no manifest to read. If preseason games ever arrive with a
    null stage, this is where that assumption breaks.
    """
    null_is_regular = "OR g.stage IS NULL" if stage == REGULAR else ""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""SELECT g.sl_id FROM game g
                WHERE g.league_id = (SELECT id FROM league WHERE sl_id = %s)
                  AND g.season = %s AND (g.stage = %s {null_is_regular})""",
            (int(league), str(season), stage))
        keep = {int(row[0]) for row in cursor.fetchall()}
    finally:
        cursor.close()
    return [shift for shift in shifts if shift.game_id in keep]


def team_labels() -> dict[int, str]:
    """team id -> shorthand, from the bundled manifest.

    The manifest rather than the database on purpose: it ships with the repo,
    so a team name costs no query, and it is metadata that neither the events
    nor the shifts carry.
    """
    import json
    path = Path(__file__).resolve().parents[1] / "manifests" / "teams.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    teams = data.get("teams", data) if isinstance(data, dict) else data
    out: dict[int, str] = {}
    for team in teams:
        try:
            team_id = int(team["id"])
        except (KeyError, TypeError, ValueError):
            continue
        out[team_id] = (team.get("shorthand") or team.get("displayName")
                        or team.get("name") or str(team_id))
    return out


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
_IDENTITY: tuple[tuple[str, float, str], ...] = (
    ("Player", 1.95, "left"),
    ("Team", 0.70, "left"),
    ("Pos", 0.36, "left"),
    ("GP", 0.36, "right"),
    ("TOI", 0.66, "right"),
    ("TOI/GP", 0.62, "right"),
)

#: A side is a meaning; the tone is how a page should say it. For and against
#: are poles, so they take the ends of a diverging pair and the undivided
#: total takes its neutral midpoint. Which hexes those are is the page's
#: business, not this module's.
_TONES = {FOR: "cool", AGAINST: "warm", BOTH: "neutral"}


def _mmss(minutes: float) -> str:
    seconds = int(round(minutes * 60))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _units_phrase(columns: ColumnSet) -> str:
    """How to describe the mixture of totals and rates in the subtitle."""
    totals = [column.heading for column in columns if not column.rate]
    rates = [column for column in columns if column.rate]
    if not totals:
        return "rates per 60 minutes of ice time in that situation"
    if not rates:
        return "season totals"
    return (f"{', '.join(dict.fromkeys(totals))} are season totals, the rest "
            f"are per 60 minutes of ice time in that situation")


def _bands(columns: ColumnSet) -> tuple:
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
            out.append(Band(column.side.capitalize(), len(_IDENTITY) + index, 1,
                            _TONES[column.side]))
    return tuple(out)


def to_sheet(rows: Sequence[PlayerRow], missing: Sequence[str] = (), *,
             columns: ColumnSet, title: str,
             league: int | None = None, season: str | None = None,
             stage: str | None = None, context=EVEN_STRENGTH,
             min_toi: float = 0.0, subtitle: Sequence[str] | None = None,
             note: str | None = None, note_extra: str = ""):
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
            f"{len(rows)} players · {_units_phrase(columns)}"
            + (f" · at least {min_toi:g} min" if min_toi else ""),
        ) if line)
    if note is None:
        note = ("Every column counts events that happened while the player was "
                "on the ice, from the metric catalog: "
                + "; ".join(dict.fromkeys(column.describe() for column in columns))
                + ". " + (note_extra + " " if note_extra else "")
                + "TOI is in minutes, TOI/GP as mm:ss. "
                f"Generated {date.today():%Y-%m-%d}.")

    fields = tuple(Field(heading, width, align)
                   for heading, width, align in _IDENTITY)
    fields += tuple(Field(column.heading) for column in columns)

    table = tuple(
        (row.name,
         teams.get(row.team_id, str(row.team_id or "")),
         row.position,
         str(row.games_played),
         f"{row.minutes:.1f}",
         _mmss(row.toi_per_game))
        + tuple(row.cell(column) for column in columns)
        for row in rows
    )

    return Sheet(title=title, fields=fields, rows=table,
                 subtitle=tuple(subtitle), note=note, bands=_bands(columns),
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
