#!/usr/bin/python
"""On-ice metrics: catalog lanes per player or per team, over many games.

RETRIEVAL, SEPARATE FROM PRESENTATION. This module computes numbers and
returns plain data. It imports no plotting library, opens no file, and knows
nothing about pages -- ``hockey/reports/`` turns what comes out of here into a
PDF, and the game canvas does its own thing with the same catalog. It lives in
``hockey/metrics/`` because that is where aggregation ACROSS GAMES belongs;
``hockey/derive/`` filters the events of one.

THREE ATTRIBUTIONS, ONE CATALOG. A lane says WHAT happened. Who to credit it
to is a separate axis, the same way ``context_filter`` is a separate axis for
the situation -- so there is no player catalog and no WOI catalog, just one
set of 159 lanes counted under one of:

    TEAM        the event's own team           (event.team_id)
    CREDITED    the player who did it          (event.player_id)
    FOR         a player on the ice, his team's event
    AGAINST     a player on the ice, the opponent's event
    BOTH        a player on the ice, either team's event

CREDITED and the three on-ice values answer different questions about the same
player: over one season player 24417 was credited with 405 shot attempts and
was on the ice for 2,502.

:func:`lane_counts` is the short way in -- give it games, players, lanes and an
attribution, get back ``{player: {lane: count}}``. :func:`player_rows` is the
long way, adding ice time and per-60 rates, which is what a report wants.
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

#: The fourth attribution, and the only one that is not about being on the ice:
#: the event is credited to THIS player (``event.player_id``). A player is
#: necessarily on the ice for what he does, so CREDITED is a subset of BOTH --
#: 405 shot attempts against 2,502 over one season for the reference player.
#: It is what the canvas's "Player" mode counts, as against "Player WOI".
CREDITED = "credited"

#: Every attribution a Column may name.
SIDES = (FOR, AGAINST, BOTH, CREDITED)


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
        if self.side not in SIDES:
            raise ValueError(f"column {self.heading!r} has side {self.side!r}; "
                             f"expected one of {SIDES}")
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


def player_rows(conn, players: Iterable, league: int | None = None,
                season: str | None = None, *, columns: ColumnSet,
                context=EVEN_STRENGTH, stage: str | None = REGULAR,
                games: Iterable[int] | None = None,
                min_toi: float = 0.0) -> tuple[list[PlayerRow], list[str]]:
    """The numbers: ``(rows, unanswered requests)``. No page in sight.

    TWO WAYS TO SAY WHICH GAMES. Name a ``league`` and ``season`` (and
    optionally a ``stage``) and the games are the ones the requested players
    have shifts in; or pass ``games`` directly when you already have the list,
    in which case league, season and stage are ignored. The second is what
    "I have these 242 games" wants, and it skips the schedule queries.

    Players are ids, names, or anything carrying a ``player_id`` -- but a NAME
    can only be resolved against a league and season, so pass ids when you
    pass ``games`` alone.
    """
    from hockey.db.event_query import query_events
    from hockey.db.roster_query import query_rosters
    from hockey.db.shift_query import query_shifts

    if league is not None and season is not None:
        wanted, missing = _resolve_players(conn, players, league, season)
    else:
        # No league/season to resolve names against: ids only.
        wanted, missing = [], []
        for request in players:
            value = getattr(request, "player_id", request)
            if isinstance(value, int) or (isinstance(value, str) and str(value).isdigit()):
                wanted.append(int(value))
            else:
                missing.append(f"{value} — a name needs a league and season to "
                               f"resolve; pass the player id instead")
    if not wanted:
        return [], missing

    # 1. Which games. Either the caller's list, or the ones these players have
    #    shifts in -- their own shifts are the cheapest way to find out.
    if games is not None:
        game_ids = sorted({int(g) for g in games})
    else:
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
        # The sweep exists to narrow ice time to a situation. With no context
        # there is nothing to narrow, and building it would be pure cost.
        timeline = SituationTimeline(toi, roster) if context is not None else None

        # -- the denominator: ice time in the selected situation
        playing: dict[int, int] = {}
        for player_id in wanted_set & set(spans):
            player = roster.players.get(player_id)
            team_id = player.team_id if player is not None else None
            seconds = (sum(end - start for start, end in spans[player_id])
                       if timeline is None
                       else timeline.selected_seconds(spans[player_id], team_id,
                                                      context))
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
        if context is not None and not context.matches(event):
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
            on_ice = (index > 0 and player_spans[index - 1][0] <= event.t
                      < player_spans[index - 1][1])
            credited = event.player_id == player_id
            if not (on_ice or credited):
                continue
            side = FOR if team_id == event_team else AGAINST
            totals = rows[player_id].totals
            for column in hits:
                if column.side == CREDITED:
                    # Not about being on the ice: did HE do it. Checked even
                    # when the shift data puts the moment outside his shift,
                    # because an event naming him as the actor is better
                    # evidence than an interval that disagrees with it.
                    if credited:
                        totals[column.key] += (
                            WEIGHTS[column.weight](event) if column.weight else 1.0)
                    continue
                if not on_ice or column.side not in (side, BOTH):
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


# --- The short way in ------------------------------------------------------

def lane_counts(conn, *, games: Iterable[int], lanes: Iterable[str],
                players: Iterable = (), attribution: str = CREDITED,
                context=None, min_toi: float = 0.0) -> dict[int, dict[str, float]]:
    """``{player id: {lane key: count}}`` for these games, lanes and attribution.

    The whole of :func:`player_rows` without the report vocabulary: name the
    games, the players, the catalog lanes and how to attribute them, get
    numbers back. Ice time is not included -- :func:`player_rows` is the one
    that divides.

        # what Y did
        lane_counts(conn, games=ids, players=[Y], attribution=CREDITED,
                    lanes=["Controlled entries · All", "Shots · On Net",
                           "Dump-outs · All"])

        # what the opposition did while Y was out there
        lane_counts(conn, games=ids, players=[Y], attribution=AGAINST,
                    lanes=["Controlled entries · All"])

    ``context`` defaults to None -- every situation -- rather than to even
    strength, because a raw count is usually wanted whole. Pass
    :data:`EVEN_STRENGTH` for the narrowed version, and note it needs the
    goalie refs, which is why the events are fetched with ``with_on_ice``.
    """
    lanes = list(lanes)
    columns = ColumnSet(tuple(Column(key, key, attribution) for key in lanes))
    rows, _ = player_rows(conn, players, league=None, season=None,
                          columns=columns, context=context, stage=None,
                          games=list(games), min_toi=min_toi)
    return {row.player_id: {lane: row.totals[Column(lane, lane, attribution).key]
                            for lane in lanes}
            for row in rows}
