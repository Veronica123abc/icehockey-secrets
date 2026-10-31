#!/usr/bin/python
"""A metric cube: every catalog lane pre-counted, so asking costs nothing.

WHAT A CUBE IS. One table, built once per set of games, holding every number
the metric catalog can produce about those games:

    game_id · player_id · team_id · side · combo · period · manpower · goalies
        -> n (events), xg (expected goals)

plus a second table of the same shape minus combo and side, holding seconds of
ice time. That is the whole idea. Nothing is selected at build time, so
nothing has to be rebuilt when you change your mind.

A COMBO IS EVERY LANE ONE EVENT MATCHED, kept together. A row per lane would
answer "how many successful entries" and "how many entries with a play after"
but not "how many successful entries WITH a play after", because which lanes
an event matched together is gone once they are counted apart -- and that
intersection is what a multi-lane column or a skill-set count asks. So the
count tables carry a combo id, ``combos.csv`` says which lanes each id stands
for, and :meth:`Cube.combos_for` turns any selection into the ids to sum. It
is also the smaller layout: an event matching six lanes is one row, not six,
and a season of events shares a few hundred combinations. Measured on 8 games:
88k rows against 189k, 0.32 MB against 0.88.

TWO ATTRIBUTIONS, TWO TABLES. ``counts``/``toi`` credit a PLAYER; the event is
counted once for every skater on the ice for it, which is what an on-ice
number means. ``team_counts``/``team_toi`` credit a TEAM; the event is counted
once. The second is not derivable from the first -- summing a lane over a
team's players multiplies it by however many of them were out there, about
five -- so a team question has its own table rather than a wrong sum of the
player one. The denominators differ for the same reason: a player's is his ice
time, a team's is GAME time, so a team's per-60 is per 60 minutes of hockey
rather than per 60 skater-minutes.

WHY IT EXISTS. :func:`~hockey.metrics.on_ice.player_rows` answers one question
per run: it takes a ``ColumnSet``, fetches only the events those columns need,
and credits only the players asked for. That is right for a report, where the
question is fixed and printed at the top of the page. It is wrong for an
afternoon of exploring, where the question changes every thirty seconds and
the run takes twelve. Measured on 8 games: 0.5s for the shooting report's
twelve columns, 12.1s for all 171 lanes on both sides.

The twelve-second version is the one worth caching, because of an accident of
how the credit loop already works -- it evaluates EVERY lane of an event's
population regardless of which columns were asked for::

    lanes = catalog.BY_EVENT.get(event.name)
    matched = {lane.key for lane in lanes if lane.matches(event)}
    hits = columns.hits(matched)          # and then throws most of it away

So a narrow question does not cost less predicate work than a wide one. Ask
for everything once, keep it, and every question after that is a groupby.

CONTEXT IS A DIMENSION, NOT A PARAMETER. The situation an event happened in is
stored beside it rather than filtered out, so switching from even strength to
the power play is a selection on a DataFrame and not another twelve seconds.
This is the same trick ``game_canvas`` plays by packing period/manpower/goalies
into one int and shipping it to the browser; here they stay three readable
columns, because a DataFrame is not a wire format and ``"ES"`` reads better
than ``311``.

GAME_ID IS A DIMENSION TOO, and it is the one that makes an arbitrary cohort
free. "The games he ate an ice-cream before the first faceoff" is not a query
any database can answer -- the list lives on an envelope -- but once the cube
is built it is ``cube.slice(games=ICE_CREAM_DAYS)`` and it returns in
milliseconds. Build the season once; select the cohort afterwards.

WHAT IT CANNOT ANSWER. The cube is pre-aggregated, so its dimensions are a
commitment. Anything outside them is gone: shot coordinates, event times, who
the opponent was, and any question about ORDER ("after a faceoff win", "the
shift following a penalty kill"). Those need the events, and
:func:`hockey.db.event_query.query_events` is still there for them. What the
cube covers is counts, sums and the ratios between them -- which is most of
what exploring actually consists of.

THE NUMBERS ARE THE REPORTS' NUMBERS. Ice time comes from the same
``SituationTimeline`` walk as :meth:`~hockey.metrics.on_ice_spans
.SituationTimeline.selected_seconds`, bucketed instead of filtered; events are
credited by the same strict shift containment as
:func:`~hockey.metrics.on_ice._credit`; xG is ``WEIGHTS["xg_official"]``, the
supplier's published figure rather than the feed's raw one. :func:`main`
re-checks that against ``player_rows`` every time it runs, because a cube that
quietly disagreed with the reports would be worse than no cube.
"""
from __future__ import annotations

import json
import time
import warnings
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from functools import cached_property
from pathlib import Path

import pandas as pd

from hockey.derive import context_filter as ctx
from hockey.derive import metric_catalog as catalog
from hockey.metrics.on_ice import WEIGHTS
from hockey.metrics.on_ice_spans import SituationTimeline
from hockey.model.events import Event
from hockey.model.roster import Roster
from hockey.model.toi import Span, skater_spans

#: Which bench a row counts, for a player on the ice. ``credited`` is the
#: fourth attribution and the only one that is not about being on the ice: the
#: event names this player as the actor. The undivided on-ice total (``BOTH``
#: in the report vocabulary) is ``for + against`` summed at query time, which
#: is why it is not stored.
FOR, AGAINST, CREDITED = "for", "against", "credited"
SIDES = (FOR, AGAINST, CREDITED)

#: A dimension the event could not say. Stored rather than dropped, so nothing
#: disappears silently -- and excluded by any narrowing slice, exactly as
#: ``ContextFilter.matches_situation`` excludes a ``None``.
UNKNOWN = "?"

#: The one population whose xG means anything. ``_xg_official`` raises an
#: ungraded SLOT shot to a grade C chance, and its slot predicate reads
#: coordinates -- which a pass also has. Asking it about a pass would invent
#: expected goals for a pass, so only shots are asked.
_SHOT = "shot"
_XG = WEIGHTS["xg_official"]

_SITUATION = ("period", "manpower", "goalies")
_COUNT_COLUMNS = ("game_id", "player_id", "team_id", "side", "combo",
                  *_SITUATION, "n", "xg")
_TOI_COLUMNS = ("game_id", "player_id", "team_id", *_SITUATION, "seconds")
_TEAM_COUNT_COLUMNS = ("game_id", "team_id", "side", "combo", *_SITUATION, "n", "xg")
#: combo id -> the lane keys an event matched, joined by :data:`_LANE_SEP`.
_COMBO_COLUMNS = ("combo", "lanes")
#: No lane key contains it; the catalog's keys use " · ".
_LANE_SEP = "|"
_TEAM_TOI_COLUMNS = ("game_id", "team_id", *_SITUATION, "seconds")
#: One row per game: when it was played, who played it, how it ended. Not a
#: metric -- it is what lets a game be NAMED, which a picker offering 52 of
#: them needs and a bare id cannot do.
_GAME_COLUMNS = ("game_id", "date", "home_team_id", "away_team_id",
                 "home_goals", "away_goals", "stage")
_CATEGORICAL = ("side", *_SITUATION)

#: :attr:`Cube.credited` of a cube saved before whom it credits was recorded.
#: Not None: None is a recorded answer, "everyone".
UNRECORDED = object()

#: :meth:`Cube.extend`'s default: credit whoever the cube already credits.
_AS_BUILT = object()


# --- Building --------------------------------------------------------------

def _or_unknown(value: str | None) -> str:
    return UNKNOWN if value is None else value


def _toi_buckets(spans: Sequence[Span], team_id: int | None,
                 slices: Sequence[tuple], starts: Sequence[float],
                 ) -> dict[tuple[str, str, str], float]:
    """Seconds on the ice, split by the situation they were played in.

    The same walk as ``SituationTimeline.selected_seconds``, bucketed instead
    of filtered -- so summing any set of buckets gives exactly the denominator
    that context would have produced. A stretch the timeline could not
    classify from this team's side is dropped here too (one team on the ice is
    a gap in the data, not a 5v0).
    """
    out: dict[tuple[str, str, str], float] = defaultdict(float)
    if team_id is None or not slices:
        return out
    for start, end in spans:
        index = max(bisect_right(starts, start) - 1, 0)
        while index < len(slices) and slices[index][0] < end:
            low, high, situations = slices[index]
            index += 1
            overlap = min(high, end) - max(low, start)
            if overlap <= 0:
                continue
            situation = situations.get(team_id)
            if situation is not None:
                out[situation] += overlap
    return out


def _game_info(conn, game_ids: Sequence[int]) -> pd.DataFrame:
    """When each game was played, and between whom.

    The one thing a cube needs that neither the events, the shifts nor the
    roster carry. ``scheduled_time`` is kept as a full ISO string so it sorts
    lexicographically after a CSV round trip, and the team ids are translated
    to SportLogIQ ids here -- the `game` table stores its own.
    """
    if not game_ids:
        return pd.DataFrame(columns=list(_GAME_COLUMNS))
    placeholders = ", ".join(["%s"] * len(game_ids))
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""SELECT g.sl_id, g.scheduled_time, h.sl_id, a.sl_id,
                       g.home_team_goals, g.away_team_goals, g.stage
                FROM game g
                LEFT JOIN team h ON h.id = g.home_team_id
                LEFT JOIN team a ON a.id = g.away_team_id
                WHERE g.sl_id IN ({placeholders})""",
            tuple(game_ids))
        rows = [(int(sl), when.isoformat() if when is not None else "",
                 home, away, goals_h, goals_a, stage or "")
                for sl, when, home, away, goals_h, goals_a, stage
                in cursor.fetchall()]
    finally:
        cursor.close()
    frame = pd.DataFrame(rows, columns=list(_GAME_COLUMNS))
    return frame.sort_values("date").reset_index(drop=True)


def _identity(player) -> tuple[str, str]:
    first = (player.first_name or "").strip()
    last = (player.last_name or "").strip()
    return (" ".join(p for p in (first, last) if p) or str(player.player_id),
            player.position or "")


def build_cube(conn, games: Iterable[int], *, players: Iterable[int] | None = None,
               progress: bool = True) -> "Cube":
    """Count every lane of every game, for every skater on the ice.

    ``players`` limits WHO gets credited -- the skaters of one team, say. It
    does not narrow what is counted: the for/against split still carries
    everything the opponent did while they were out there, which is the
    question an opponent's own row would have answered anyway. On a season it
    is the difference between ~40 skaters a game and the dozen you care about,
    so pass it when the cube is for one team and leave it out when you want
    the league.

    Three bulk reads and one pass over the events. ``with_on_ice=True`` is not
    optional: the goalie refs live in the on-ice reconstruction and
    ``context_filter.goalies_of`` reads them, so without it every net would
    classify as empty. That read is also the expensive part -- it rebuilds
    on-ice sets for every event of every game -- which is the main reason a
    cube is built once and saved rather than rebuilt per question.

    ``players`` is kept on the cube as :attr:`Cube.credited`, so that
    :meth:`Cube.extend` credits later games the same way without being told.

    Progress is printed per game because a season takes minutes; pass
    ``progress=False`` for silence.
    """
    from hockey.db.event_query import query_events
    from hockey.db.roster_query import query_rosters
    from hockey.db.shift_query import query_shifts

    game_ids = sorted({int(g) for g in games})
    if not game_ids:
        raise ValueError("a cube needs at least one game")
    wanted = None if players is None else {int(p) for p in players}

    started = time.perf_counter()
    shifts_by_game: dict[int, list] = defaultdict(list)
    for interval in query_shifts(conn, game_sl_ids=game_ids):
        shifts_by_game[interval.game_id].append(interval)
    rosters = query_rosters(conn, game_sl_ids=game_ids)
    events_by_game: dict[int, list[Event]] = defaultdict(list)
    for event in query_events(conn, game_sl_ids=game_ids,
                              names=list(catalog.BY_EVENT), with_on_ice=True):
        events_by_game[event.game_id].append(event)
    fetched = time.perf_counter() - started
    if progress:
        print(f"   fetched {sum(len(e) for e in events_by_game.values()):,} events, "
              f"{sum(len(s) for s in shifts_by_game.values()):,} shifts "
              f"for {len(game_ids)} games in {fetched:.1f}s")

    counts: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0])
    seconds: dict[tuple, float] = defaultdict(float)
    team_counts: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0])
    team_seconds: dict[tuple, float] = defaultdict(float)
    combos: dict[tuple[str, ...], int] = {}
    benches: dict[tuple[int, int], int | None] = {}
    identities: dict[int, tuple[str, str]] = {}

    for number, game_id in enumerate(game_ids, start=1):
        toi = shifts_by_game.get(game_id, [])
        roster = rosters.get(game_id)
        if not toi or roster is None:
            warnings.warn(f"game {game_id}: no shifts or no roster, skipped",
                          stacklevel=2)
            continue
        spans = skater_spans(toi, roster)
        timeline = SituationTimeline(toi, roster)
        starts = [low for low, _, _ in timeline.slices]

        # -- the TEAM denominator: GAME time in each situation. A team is on
        #    the ice for all of it, so this is the game clock swept through the
        #    timeline from that bench's side -- not the sum of its skaters'
        #    ice time, which would be about five times larger. Both benches,
        #    because the opponent's row is what makes a team's row readable.
        #    A game that does not show exactly two benches is a gap in the
        #    data, and team_rows skips it for the same reason.
        team_pair = sorted({player.team_id for player in roster.players.values()
                            if player.team_id is not None})
        if len(team_pair) != 2:
            team_pair = []
        end_of_game = max((x.end_t for x in toi if x.end_t is not None), default=0.0)
        for team_id in team_pair:
            for situation, overlap in _toi_buckets([(0.0, end_of_game)], team_id,
                                                   timeline.slices, starts).items():
                team_seconds[(game_id, team_id) + situation] += overlap

        # -- the player denominator, split by situation rather than narrowed
        on_ice_players: list[tuple[int, int | None, list[Span]]] = []
        for player_id, player_spans in spans.items():
            if wanted is not None and player_id not in wanted:
                continue
            player = roster.players.get(player_id)
            team_id = player.team_id if player is not None else None
            benches[(game_id, player_id)] = team_id
            if player is not None and player_id not in identities:
                identities[player_id] = _identity(player)
            on_ice_players.append((player_id, team_id, player_spans))
            for situation, overlap in _toi_buckets(player_spans, team_id,
                                                   timeline.slices, starts).items():
                seconds[(game_id, player_id) + situation] += overlap

        # -- the numerators. The lane predicates are evaluated once per event,
        #    not once per player: the inner loop is the P x E term.
        for event in events_by_game.get(game_id, []):
            event_team = ctx.team_of(event)
            if event.t is None or event_team is None:
                continue
            lanes = catalog.BY_EVENT.get(event.name)
            if not lanes:
                continue
            matched = tuple(lane.key for lane in lanes if lane.matches(event))
            if not matched:
                continue
            # The whole set of lanes this event matched, as one id: what lets
            # a lane ANDed with another be counted later, which a row per lane
            # could not. Catalog order, so equal sets get the same id.
            combo = combos.setdefault(matched, len(combos))
            situation = (_or_unknown(ctx.period_of(event)),
                         _or_unknown(ctx.manpower_of(event)),
                         _or_unknown(ctx.goalies_of(event)))
            xg = _XG(event) if event.name == _SHOT else 0.0
            actor = event.player_id
            moment = (event.t, float("inf"))

            # Once per team, before the per-skater loop below: this is the
            # same event, counted once rather than once per man on the ice.
            for team_id in team_pair:
                team_side = FOR if team_id == event_team else AGAINST
                cell = team_counts[(game_id, team_id, team_side, combo) + situation]
                cell[0] += 1.0
                cell[1] += xg

            for player_id, team_id, player_spans in on_ice_players:
                index = bisect_right(player_spans, moment)
                on_ice = (index > 0 and player_spans[index - 1][0] <= event.t
                          < player_spans[index - 1][1])
                sides = []
                if on_ice:
                    # Strict containment, as the reports use: the shift has to
                    # contain the moment. skater.py is deliberately looser.
                    sides.append(FOR if team_id == event_team else AGAINST)
                if player_id == actor:
                    sides.append(CREDITED)
                for side in sides:
                    cell = counts[(game_id, player_id, side, combo) + situation]
                    cell[0] += 1.0
                    cell[1] += xg
        if progress and (number % 10 == 0 or number == len(game_ids)):
            print(f"   {number}/{len(game_ids)} games "
                  f"({time.perf_counter() - started:.1f}s)")

    count_frame = pd.DataFrame(
        [(game, player, benches.get((game, player)), side, combo,
          period, manpower, goalies, int(n), round(xg, 4))
         for (game, player, side, combo, period, manpower, goalies), (n, xg)
         in counts.items()],
        columns=list(_COUNT_COLUMNS))
    toi_frame = pd.DataFrame(
        [(game, player, benches.get((game, player)),
          period, manpower, goalies, value)
         for (game, player, period, manpower, goalies), value in seconds.items()],
        columns=list(_TOI_COLUMNS))
    team_count_frame = pd.DataFrame(
        [(game, team, side, combo, period, manpower, goalies, int(n), round(xg, 4))
         for (game, team, side, combo, period, manpower, goalies), (n, xg)
         in team_counts.items()],
        columns=list(_TEAM_COUNT_COLUMNS))
    team_toi_frame = pd.DataFrame(
        [(game, team, period, manpower, goalies, value)
         for (game, team, period, manpower, goalies), value in team_seconds.items()],
        columns=list(_TEAM_TOI_COLUMNS))
    game_frame = _game_info(conn, game_ids)
    player_frame = pd.DataFrame(
        [(player_id, name, position)
         for player_id, (name, position) in sorted(identities.items())],
        columns=["player_id", "name", "position"])

    combo_frame = pd.DataFrame(
        [(combo, _LANE_SEP.join(matched)) for matched, combo in combos.items()],
        columns=list(_COMBO_COLUMNS))

    return Cube(counts=_typed(count_frame), toi=_typed(toi_frame),
                players=player_frame, games=tuple(game_ids),
                team_counts=_typed(team_count_frame),
                team_toi=_typed(team_toi_frame), game_info=game_frame,
                combos=combo_frame,
                credited=None if wanted is None else tuple(sorted(wanted)),
                built=date.today().isoformat())


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    """Narrow dtypes. A season is a few hundred thousand rows and the side
    and situation columns repeat endlessly, so categoricals pay."""
    frame = frame.copy()
    if "team_id" in frame.columns:
        frame["team_id"] = frame["team_id"].astype("Int64")
    for column in ("n", "combo"):
        if column in frame.columns:
            frame[column] = frame[column].astype("int32")
    for column in _CATEGORICAL:
        if column in frame.columns:
            frame[column] = frame[column].astype("category")
    return frame


# --- Using -----------------------------------------------------------------

@dataclass(frozen=True)
class Cube:
    """Counted lanes and ice time for a set of games, sliceable for free.

    ``counts`` and ``toi`` share their situation columns, so every slice
    narrows both and a rate always divides like with like; ``team_counts`` and
    ``team_toi`` are the same pair for the other attribution. ``players`` is
    kept separate rather than denormalised into a quarter of a million rows;
    use :attr:`names` to label a result for printing.
    """
    counts: pd.DataFrame
    toi: pd.DataFrame
    players: pd.DataFrame
    games: tuple[int, ...]
    team_counts: pd.DataFrame = field(default_factory=pd.DataFrame)
    team_toi: pd.DataFrame = field(default_factory=pd.DataFrame)
    game_info: pd.DataFrame = field(default_factory=pd.DataFrame)
    combos: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=list(_COMBO_COLUMNS)))
    #: Saved before combinations were kept: every combo is one lane, so a
    #: selection of several lanes would be a sum where it must be an
    #: intersection. :meth:`combos_for` refuses those rather than guessing.
    per_lane: bool = False
    #: Whom the cube credits: None for every skater on the ice, or the player
    #: ids it was built for -- ``build_cube``'s ``players``, kept so that
    #: :meth:`extend` credits the new games the same way. :data:`UNRECORDED`
    #: for a cube saved before this was kept.
    credited: tuple[int, ...] | None | object = UNRECORDED
    built: str = ""

    def __repr__(self) -> str:
        span = ""
        if len(self.game_info) and self.game_info.date.any():
            dates = sorted(d[:10] for d in self.game_info.date if d)
            span = f" {dates[0]}..{dates[-1]}," if dates else ""
        present = self._lane_table[self._lane_table.combo.isin(self.counts.combo)]
        return (f"Cube({len(self.games)} games,{span} {len(self.players)} players, "
                f"{present.lane.nunique()} lanes, "
                f"{len(self.counts):,} player rows + {len(self.team_counts):,} "
                f"team rows, {self.minutes:.0f} player-minutes)")

    # -- labels ------------------------------------------------------------

    @property
    def names(self) -> dict[int, str]:
        """player id -> name, for ``.rename(index=cube.names)``."""
        return dict(zip(self.players.player_id, self.players.name))

    @property
    def team_names(self) -> dict[int, str]:
        """team id -> shorthand, from the bundled manifest."""
        from hockey.metrics.on_ice import team_labels
        return team_labels()

    @property
    def minutes(self) -> float:
        """Player-minutes: the sum of everyone's ice time, so five skaters on
        the ice for a minute is five. :attr:`team_minutes` is the clock."""
        return float(self.toi.seconds.sum()) / 60.0

    @property
    def team_minutes(self) -> float:
        """Minutes of hockey, counted once per team."""
        return float(self.team_toi.seconds.sum()) / 60.0 if len(self.team_toi) else 0.0

    # -- lanes -------------------------------------------------------------

    @cached_property
    def _members(self) -> dict[int, frozenset[str]]:
        """combo id -> the lanes it stands for."""
        return {int(combo): frozenset(lanes.split(_LANE_SEP))
                for combo, lanes in zip(self.combos.combo, self.combos.lanes)}

    @cached_property
    def _lane_table(self) -> pd.DataFrame:
        """One row per (combo, lane): the join that turns combos into lanes."""
        return pd.DataFrame(
            [(combo, lane) for combo, lanes in self._members.items()
             for lane in lanes], columns=["combo", "lane"]).astype({"combo": "int32"})

    def combos_for(self, lanes: str | Iterable[str]) -> list[int]:
        """The combos a selection of lanes counts, under the
        :class:`~hockey.metrics.on_ice.Column` contract: OR within a filter
        group, AND across groups.

        Summing the rows of these combos counts each event once, however many
        of the selected lanes it matched -- which is why OR within a group is
        right here even where a group's items overlap.
        """
        lanes = (lanes,) if isinstance(lanes, str) else tuple(lanes)
        unknown = [key for key in lanes if key not in catalog.BY_KEY]
        if unknown:
            raise KeyError(f"unknown lane(s) {unknown}; run "
                           f"`python -m hockey.derive.metric_catalog` for the tree")
        if self.per_lane and len(lanes) > 1:
            raise ValueError(
                f"this cube was saved one row per lane, before combinations "
                f"were kept, so {list(lanes)} cannot be combined; rebuild it")
        by_group: dict[str, set[str]] = {}
        for key in lanes:
            by_group.setdefault(catalog.BY_KEY[key].group or "", set()).add(key)
        groups = list(by_group.values())
        return [combo for combo, members in self._members.items()
                if all(members & group for group in groups)]

    def _by_lane(self, rows: pd.DataFrame, index: str, value: str) -> pd.DataFrame:
        """``index`` x lanes from combo rows: each combo credited to every
        lane it stands for."""
        if not len(rows):
            return pd.DataFrame()
        per_combo = (rows.groupby([index, "combo"], observed=True)[value].sum()
                     .reset_index())
        return per_combo.merge(self._lane_table, on="combo").pivot_table(
            index=index, columns="lane", values=value, aggfunc="sum",
            fill_value=0.0)

    # -- narrowing ---------------------------------------------------------

    def slice(self, *, games: Iterable[int] | None = None,
              players: Iterable[int] | None = None,
              teams: Iterable[int] | None = None,
              periods: Iterable[str] | None = None,
              manpower: Iterable[str] | None = None,
              goalies: Iterable[str] | None = None) -> "Cube":
        """A cube narrowed on any of the shared dimensions. None means keep all.

        ``teams`` filters by the PLAYER's bench, which is a different axis from
        ``ContextFilter.teams`` (the event's team) -- the for/against split
        already carries that relation.

        ``side`` and ``lane`` are deliberately absent: those are what you
        SELECT, in :meth:`wide` or in pandas, and narrowing them here would
        suggest the ice time had narrowed with them.

        WHICH TABLES EACH ARGUMENT TOUCHES. ``games``, ``teams`` and the three
        situation arguments narrow both attributions. ``players`` narrows only
        the player tables -- a team's total does not depend on which of its
        skaters you were looking at, and quietly rewriting it to the selected
        players' teams would be a surprise rather than a convenience.
        """
        frames = {"counts": self.counts, "toi": self.toi,
                  "team_counts": self.team_counts, "team_toi": self.team_toi}
        narrowing = (("game_id", games, True), ("player_id", players, False),
                     ("team_id", teams, True), ("period", periods, True),
                     ("manpower", manpower, True), ("goalies", goalies, True))
        for column, values, both in narrowing:
            if values is None:
                continue
            wanted = list(values)
            for name, frame in frames.items():
                if not both and name.startswith("team_"):
                    continue
                if column in frame.columns:
                    frames[name] = frame[frame[column].isin(wanted)]
        counts, toi = frames["counts"], frames["toi"]
        kept = set(counts.player_id) | set(toi.player_id)
        game_ids = sorted(set(toi.game_id) | set(counts.game_id))
        info = self.game_info
        if len(info):
            info = info[info.game_id.isin(game_ids)]
        credited = self.credited
        if players is not None and credited is not UNRECORDED:
            chosen = {int(p) for p in players}
            credited = tuple(sorted(chosen if credited is None
                                    else chosen & set(credited)))
        return Cube(counts=counts, toi=toi,
                    players=self.players[self.players.player_id.isin(kept)],
                    games=tuple(game_ids),
                    team_counts=frames["team_counts"], team_toi=frames["team_toi"],
                    game_info=info, combos=self.combos, per_lane=self.per_lane,
                    credited=credited, built=self.built)

    def slice_context(self, context) -> "Cube":
        """The slice a :class:`~hockey.derive.context_filter.ContextFilter`
        selects -- so a cube and a report narrow by one definition, not two.

        ``context.teams`` is NOT applied: it selects the event's team, and in a
        cube that relation is the for/against side. Pass ``teams=`` to
        :meth:`slice` to choose whose players you want.
        """
        if getattr(context, "teams", None) is not None:
            warnings.warn("context.teams selects the EVENT's team and has no "
                          "cube meaning; ignored. Use slice(teams=...) to pick "
                          "players by bench.", stacklevel=2)
        return self.slice(periods=None if context.all_periods else list(context.periods),
                          manpower=list(context.manpower),
                          goalies=list(context.goalies))

    # -- reading -----------------------------------------------------------

    def summary(self) -> pd.DataFrame:
        """One row per player: games, minutes, minutes per game. The sample."""
        grouped = (self.toi.groupby("player_id", observed=True)
                   .agg(games=("game_id", "nunique"), seconds=("seconds", "sum"),
                        # His bench in the last game of the slice: a traded
                        # player has two, and the latest is the useful one.
                        team_id=("team_id", "last")))
        grouped["minutes"] = grouped.seconds / 60.0
        grouped["min_per_game"] = grouped.minutes / grouped.games
        out = grouped.join(self.players.set_index("player_id")[["name", "position"]])
        return out[["name", "position", "team_id", "games", "minutes",
                    "min_per_game"]].sort_values("minutes", ascending=False)

    def wide(self, *, side: str = FOR, value: str = "n",
             per60: bool = False, min_minutes: float = 0.0) -> pd.DataFrame:
        """players x lanes. THE object to explore: 171 columns, one per lane.

        ``value`` is ``"n"`` (events) or ``"xg"``. ``per60`` divides by this
        slice's own ice time, which is the only denominator that means
        anything -- even-strength events over even-strength minutes.

        Everything pandas does to a DataFrame now applies to the whole metric
        catalog at once: ``.corr()``, ``.rank()``, ``.idxmax()``, sorting by a
        column, subtracting the team median.
        """
        if side not in SIDES:
            raise ValueError(f"side {side!r}; expected one of {SIDES}")
        table = self._by_lane(self.counts[self.counts.side == side],
                              "player_id", value)
        minutes = self.summary()[["minutes"]]
        table = table.join(minutes, how="outer").fillna(0.0)
        table = table[table.minutes > min_minutes]
        hours = table.pop("minutes") / 60.0
        if per60:
            table = table.div(hours.where(hours > 0), axis=0).fillna(0.0)
        return table.sort_index(axis=1)

    def total(self, lane: str | Iterable[str], *, side: str = FOR,
              value: str = "n") -> float:
        """One number: this lane, this side, summed over whatever is sliced.

        The short way to ask a question whose answer is a single figure --
        ``cube.total("Passes · Successful", side=CREDITED)``. Several lanes
        combine as :meth:`combos_for` says.
        """
        rows = self.counts[self.counts.combo.isin(self.combos_for(lane))
                           & (self.counts.side == side)]
        return float(rows[value].sum())

    def player_totals(self, lanes: str | Iterable[str], *,
                      sides: str | Iterable[str] = FOR,
                      value: str = "n") -> pd.Series:
        """player id -> total of a selection of lanes, on one or more sides.

        What a report column or a skill-set count needs: :meth:`total` per
        player. ``sides=(FOR, AGAINST)`` is the undivided on-ice total.
        Players with nothing selected are absent rather than zero.
        """
        sides = [sides] if isinstance(sides, str) else list(sides)
        rows = self.counts[self.counts.combo.isin(self.combos_for(lanes))
                           & self.counts.side.isin(sides)]
        return rows.groupby("player_id", observed=True)[value].sum()

    def game_table(self) -> pd.DataFrame:
        """The games, in the order they were played, named rather than numbered.

        What a game picker shows and what a notebook wants when choosing a
        cohort: ``cube.game_table().head(10).game_id`` is "the first ten".
        """
        if not len(self.game_info):
            return pd.DataFrame(columns=["game_id", "date", "label", "score"])
        names = self.team_names
        out = self.game_info.copy()
        out["day"] = [str(d)[:10] for d in out.date]
        out["label"] = [
            f"{names.get(home, home)} – {names.get(away, away)}"
            for home, away in zip(out.home_team_id, out.away_team_id)]
        out["score"] = [
            "" if pd.isna(h) or pd.isna(a) else f"{int(h)}–{int(a)}"
            for h, a in zip(out.home_goals, out.away_goals)]
        return out[["game_id", "day", "label", "score", "stage"]] \
            .rename(columns={"day": "date"}).reset_index(drop=True)

    # -- reading, the other attribution ------------------------------------

    def team_summary(self) -> pd.DataFrame:
        """One row per team: games and MINUTES OF HOCKEY in this slice.

        Not comparable with :meth:`summary`'s minutes, and deliberately named
        differently: a team's 60 minutes is the clock, a player's is his shifts.
        """
        if not len(self.team_toi):
            return pd.DataFrame(columns=["name", "games", "minutes"])
        grouped = (self.team_toi.groupby("team_id", observed=True)
                   .agg(games=("game_id", "nunique"), seconds=("seconds", "sum")))
        grouped["minutes"] = grouped.seconds / 60.0
        labels = self.team_names
        grouped["name"] = [labels.get(int(t), str(t)) for t in grouped.index]
        return grouped[["name", "games", "minutes"]].sort_values("minutes",
                                                                 ascending=False)

    def team_wide(self, *, side: str = FOR, value: str = "n",
                  per60: bool = False, labels: bool = True) -> pd.DataFrame:
        """teams x lanes, the team answer to :meth:`wide`.

        ``per60`` divides by game time, so a figure here is about a fifth of
        the same lane summed over the team's skaters -- which is the whole
        reason this table exists separately.

        ``labels=False`` keeps team ids on the index instead of shorthands, so
        a caller joining this to :meth:`team_summary` matches on the id rather
        than on a name two clubs might share.
        """
        if side not in (FOR, AGAINST):
            raise ValueError(f"side {side!r}; a team event is for or against, "
                             f"never credited -- that asks which PLAYER did it")
        table = self._by_lane(self.team_counts[self.team_counts.side == side],
                              "team_id", value)
        if not len(table):
            return pd.DataFrame()
        hours = (self.team_summary().minutes / 60.0).reindex(table.index)
        if per60:
            table = table.div(hours.where(hours > 0), axis=0).fillna(0.0)
        table = table.sort_index(axis=1)
        if not labels:
            return table
        names = self.team_names
        return table.rename(index={t: names.get(int(t), str(t))
                                   for t in table.index})

    def team_total(self, lane: str | Iterable[str], *, side: str = FOR,
                   value: str = "n") -> float:
        """One number for the team: this lane, counted once per event."""
        rows = self.team_counts[self.team_counts.combo.isin(self.combos_for(lane))
                                & (self.team_counts.side == side)]
        return float(rows[value].sum())

    # -- growing -----------------------------------------------------------

    def extend(self, conn, games: Iterable[int], *,
               players=_AS_BUILT, progress: bool = True) -> "Cube":
        """This cube plus whichever of ``games`` it does not hold yet.

        A game is counted on its own, so last week's games never need
        counting again: after a round, pass the season's schedule and only
        the new games are built.

        The new games credit whoever the cube already credits
        (:attr:`credited`). Pass ``players`` only to change that list -- a
        roster that gained a player, say; the cube then credits both lists.
        A cube that credits everyone cannot be extended with a list, nor one
        with a list by everyone: half its games would mean something else.
        A cube saved before :attr:`credited` was kept needs ``players``
        (None for everyone), and records it from then on.
        """
        if players is _AS_BUILT:
            if self.credited is UNRECORDED:
                raise ValueError("this cube does not record whom it credits; "
                                 "pass players= (None for everyone) or rebuild it")
            players = self.credited
        listed = None if players is None else {int(p) for p in players}
        if self.credited is UNRECORDED or (self.credited is None and listed is None):
            credited = None if listed is None else tuple(sorted(listed))
        elif (self.credited is None) != (listed is None):
            raise ValueError(
                "this cube credits " + ("everyone" if self.credited is None
                                        else f"{len(self.credited)} players")
                + "; extending it crediting " + ("everyone" if listed is None
                                                 else f"{len(listed)} players")
                + " would mix two kinds of cube -- rebuild it instead")
        else:
            credited = tuple(sorted(set(self.credited) | listed))

        held = set(self.games)
        new = sorted({int(g) for g in games} - held)
        if not new:
            return replace(self, credited=credited)
        return replace(_concat(self, build_cube(conn, new, players=listed,
                                                progress=progress)),
                       credited=credited)

    # -- keeping -----------------------------------------------------------

    def save(self, directory: Path | str) -> Path:
        """CSVs and a note saying what was built, when, from which games.

        Gzipped, which pandas does from the suffix alone. The side and
        situation columns are the same few strings repeated hundreds of
        thousands of times, so it is a tenfold saving for nothing -- a season
        is a few MB rather than a few hundred. ``combos.csv`` is what the
        combo ids in the two count tables mean.
        """
        if self.per_lane:
            raise ValueError("a per-lane cube cannot be saved in the combined "
                             "format it does not hold; rebuild it")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.counts.to_csv(directory / "counts.csv.gz", index=False)
        self.toi.to_csv(directory / "toi.csv.gz", index=False)
        self.team_counts.to_csv(directory / "team_counts.csv.gz", index=False)
        self.team_toi.to_csv(directory / "team_toi.csv.gz", index=False)
        self.game_info.to_csv(directory / "games.csv", index=False)
        self.players.to_csv(directory / "players.csv", index=False)
        self.combos.to_csv(directory / "combos.csv", index=False)
        (directory / "meta.json").write_text(json.dumps({
            "games": list(self.games), "built": self.built,
            "lanes": int(self._lane_table.lane.nunique()),
            "combos": len(self.combos),
            "count_rows": len(self.counts), "toi_rows": len(self.toi),
            "team_count_rows": len(self.team_counts),
            **({} if self.credited is UNRECORDED else
               {"credited": None if self.credited is None
                else list(self.credited)}),
        }, indent=2), encoding="utf-8")
        return directory

    @classmethod
    def load(cls, directory: Path | str) -> "Cube":
        directory = Path(directory)
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        counts = pd.read_csv(directory / "counts.csv.gz")
        team_counts = _read_optional(directory / "team_counts.csv.gz",
                                     _TEAM_COUNT_COLUMNS)
        per_lane = not (directory / "combos.csv").is_file()
        if per_lane:
            # Saved one row per lane: give each lane a combo of its own, which
            # answers every single-lane question exactly and no other.
            warnings.warn(f"{directory.name} was saved one row per lane; lanes "
                          f"cannot be combined until it is rebuilt",
                          stacklevel=2)
            lanes = sorted(set(counts.lane) | set(team_counts.get("lane", ())))
            ids = {lane: number for number, lane in enumerate(lanes)}
            counts = counts.assign(combo=counts.lane.map(ids)).drop(columns="lane")
            if "lane" in team_counts.columns:
                team_counts = (team_counts.assign(combo=team_counts.lane.astype(str)
                                                  .map(ids))
                               .drop(columns="lane"))
            combos = pd.DataFrame(list(enumerate(lanes)),
                                  columns=list(_COMBO_COLUMNS))
        else:
            combos = pd.read_csv(directory / "combos.csv")
        return cls(counts=_typed(counts),
                   toi=_typed(pd.read_csv(directory / "toi.csv.gz")),
                   players=pd.read_csv(directory / "players.csv"),
                   games=tuple(meta["games"]),
                   team_counts=_typed(team_counts),
                   team_toi=_read_optional(directory / "team_toi.csv.gz",
                                           _TEAM_TOI_COLUMNS),
                   game_info=_read_optional(directory / "games.csv",
                                            _GAME_COLUMNS),
                   combos=combos, per_lane=per_lane,
                   credited=(UNRECORDED if "credited" not in meta
                             else None if meta["credited"] is None
                             else tuple(int(p) for p in meta["credited"])),
                   built=meta.get("built", ""))


def _concat(old: Cube, new: Cube) -> Cube:
    """Two cubes over different games as one, ``new``'s combo ids translated
    to ``old``'s by the lanes they stand for."""
    ids = {lanes: int(combo) for combo, lanes in zip(old.combos.combo,
                                                     old.combos.lanes)}
    next_id = max(ids.values(), default=-1) + 1
    remap: dict[int, int] = {}
    for combo, lanes in zip(new.combos.combo, new.combos.lanes):
        if lanes not in ids:
            ids[lanes] = next_id
            next_id += 1
        remap[int(combo)] = ids[lanes]
    combos = pd.DataFrame([(combo, lanes) for lanes, combo in ids.items()],
                          columns=list(_COMBO_COLUMNS))

    def joined(a: pd.DataFrame, b: pd.DataFrame, translate: bool) -> pd.DataFrame:
        if translate and len(b):
            b = b.assign(combo=b.combo.map(remap))
        # astype(object) first: concatenating categoricals with different
        # categories would quietly fall back to object anyway.
        frames = [f.astype({c: object for c in _CATEGORICAL if c in f.columns})
                  for f in (a, b) if len(f)]
        return _typed(pd.concat(frames, ignore_index=True)) if frames else a

    info = pd.concat([f for f in (old.game_info, new.game_info) if len(f)],
                     ignore_index=True) if len(new.game_info) else old.game_info
    if len(info):
        info = info.sort_values("date").reset_index(drop=True)
    players = (pd.concat([old.players, new.players], ignore_index=True)
               .drop_duplicates("player_id", keep="last")
               .sort_values("player_id").reset_index(drop=True))
    return Cube(counts=joined(old.counts, new.counts, True),
                toi=joined(old.toi, new.toi, False),
                players=players,
                games=tuple(sorted(set(old.games) | set(new.games))),
                team_counts=joined(old.team_counts, new.team_counts, True),
                team_toi=joined(old.team_toi, new.team_toi, False),
                game_info=info, combos=combos, per_lane=old.per_lane,
                built=new.built)


def _read_optional(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    """A frame saved by an older cube may not be there; an empty one with the
    right columns keeps every slice and sum working rather than raising."""
    if not path.exists():
        warnings.warn(f"{path.name} missing -- this cube was saved by an older "
                      f"version; rebuild it for what that file holds",
                      stacklevel=3)
        return _typed(pd.DataFrame(columns=list(columns)))
    return _typed(pd.read_csv(path))


# --- The point of all this -------------------------------------------------

def _rule(number: int, title: str) -> None:
    print(f"\n{'=' * 78}\n{number}. {title}\n{'=' * 78}")


def main() -> None:
    """Build a cube for one team's season, then ask it six kinds of question.

    No arguments and no argparse: edit the five constants below. The sections
    are in the order the benefit arrives -- pay once, then ask freely, then
    check that the free answers are the same ones the reports give.
    """
    from hockey.db.game_query import query_game_ids
    from hockey.metrics.on_ice import (EVEN_STRENGTH, open_connection,
                                       player_rows, team_rows)
    from hockey.helpers.get_roster import get_roster
    from hockey.reports.shooting_player_woi import COLUMNS as SHOOTING

    LEAGUE, SEASON, TEAM = 13, "20252026", 323
    CUBE_DIR = Path("output/cubes") / f"team{TEAM}_{SEASON}"
    #cube = Cube.load(CUBE_DIR)
    #: "Failed shot" is not one lane -- a shot fails by missing or by being
    #: blocked. Missed is the one meant here; swap in "Shots · Blocked" to ask
    #: the other version. Nothing rebuilds.
    PASSES, SHOTS = "Passes · Successful", "Shots · Missed"

    pd.set_option("display.width", 200, "display.max_columns", 30)
    conn = open_connection()

    # ---------------------------------------------------------------- 1
    _rule(1, "BUILD IT ONCE  (the only slow step)")
    games = query_game_ids(conn, league_sl_id=LEAGUE, season=SEASON,
                           team_sl_ids=TEAM)
    print(f"{len(games)} games for team {TEAM}, {SEASON}, chronological: "
          f"{games[:5]}{' ...' if len(games) > 5 else ''}")
    started = time.perf_counter()
    cube = build_cube(conn, games, players=[p.player_id for p in get_roster(TEAM, SEASON, conn)])
    build_seconds = time.perf_counter() - started
    print(f"\n{cube}")
    print(f"built in {build_seconds:.1f}s  "
          f"-- every lane, every player, every situation, every game")

    # ---------------------------------------------------------------- 2
    _rule(2, "KEEP IT  (so tomorrow costs nothing)")
    cube.save(CUBE_DIR)
    size = sum(f.stat().st_size for f in CUBE_DIR.glob("*")) / 1e6
    print(f"saved to {CUBE_DIR}/  ({size:.1f} MB)")
    started = time.perf_counter()
    cube = Cube.load(CUBE_DIR)
    print(f"reloaded in {time.perf_counter() - started:.2f}s  "
          f"-- against {build_seconds:.1f}s to rebuild")

    summary = cube.summary()

    print(f"\n{summary.head(8).to_string(float_format='%.1f')}")
    kalle = int(summary.index[0])
    kalle_name = cube.names[kalle]

    # ---------------------------------------------------------------- 3
    _rule(3, "THE ENVELOPE QUESTION  (a cohort no query can describe)")
    ice_cream_days = list(cube.games[:3])
    other_days = [g for g in cube.games if g not in ice_cream_days]
    print(f"ice-cream days, off the back of an envelope: {ice_cream_days}")
    print(f"the other {len(other_days)} games:            {other_days}\n")

    started = time.perf_counter()
    for label, cohort in (("ice-cream days", ice_cream_days),
                          ("every other game", other_days)):
        his = cube.slice(games=cohort, players=[kalle])
        passes = his.total(PASSES, side=CREDITED)
        shots = his.total(SHOTS, side=CREDITED)
        print(f"   {label:18s}  {PASSES} {passes:6.0f}   "
              f"{SHOTS} {shots:4.0f}   ratio {passes / shots if shots else 0:6.1f}   "
              f"({his.minutes:.0f} min)")
    print(f"\nboth answers in {(time.perf_counter() - started) * 1000:.0f} ms, "
          f"for {kalle_name}. No database, no rebuild.")
    print("Change the envelope, change the lanes, change the player: same cost.")

    # ---------------------------------------------------------------- 4
    _rule(4, "EXPLORE  (171 lanes at once, looking for the non-obvious)")
    even = cube.slice_context(EVEN_STRENGTH)
    rates = even.wide(side=FOR, per60=True, min_minutes=20.0)
    print(f"wide table at even strength: {rates.shape[0]} players "
          f"x {rates.shape[1]} lanes, every cell a per-60 rate")

    median = rates.median()
    busy = median[median > 1.0].index          # lanes with enough traffic to mean something
    deviation = (rates.loc[kalle, busy] / median[busy]).sort_values(ascending=False)
    print(f"\nWhat is unusual about {kalle_name} at even strength?")
    print("(his per-60 divided by the team median, highest and lowest)\n")
    for lane, factor in list(deviation.head(6).items()) + list(deviation.tail(4).items()):
        print(f"   {factor:5.2f}x   {lane:40s}  "
              f"him {rates.loc[kalle, lane]:7.1f}  team {median[lane]:7.1f}")
    print("\nThat ranking is one line of pandas over the whole catalog. So is")
    print("rates.corr(), or rates.rank(), or sorting the team by any lane.")

    # ---------------------------------------------------------------- 5
    _rule(5, "CHANGE THE SITUATION  (context is a dimension, not a rerun)")
    for label, situation in (("even strength", dict(manpower=["ES"])),
                             ("power play",    dict(manpower=["PP1", "PP2"])),
                             ("shorthanded",   dict(manpower=["SH1", "SH2"])),
                             ("third period",  dict(periods=["P3"]))):
        his = cube.slice(players=[kalle], **situation)
        shots = his.total("Shots · All", side=FOR)
        print(f"   {label:15s} {his.minutes:6.1f} min   "
              f"shots for on ice {shots:5.0f}   "
              f"per 60 {shots / (his.minutes / 60) if his.minutes else 0:6.1f}")
    print("\nNo rebuild between those lines -- the situation was stored, not applied.")

    # ---------------------------------------------------------------- 6
    _rule(6, "THE TEAM, NOT THE PLAYERS  (counted once, not once per skater)")
    ours = cube.slice_context(EVEN_STRENGTH).slice(teams=[TEAM])
    trap = float(ours.wide(side=FOR)["Shots · All"].sum())
    truth = ours.team_total("Shots · All", side=FOR)
    print("Summing a lane over a team's players is NOT the team's number:")
    print(f"   over the 23 players' rows   {trap:6.0f}   <- each shot counted "
          f"once per skater on the ice")
    print(f"   team_counts                 {truth:6.0f}   <- each shot counted "
          f"once")
    print(f"   ratio {trap / truth:.2f}, which is roughly how many skaters a team "
          f"has on the ice.\n")
    print(f"{ours.team_summary().to_string(float_format='%.1f')}\n")

    print("So the question a coach asks first -- how did WE do -- reads:")
    for label, situation in (("even strength", dict(manpower=["ES"])),
                             ("power play",    dict(manpower=["PP1", "PP2"])),
                             ("shorthanded",   dict(manpower=["SH1", "SH2"]))):
        theirs = cube.slice(teams=[TEAM], **situation)
        minutes = theirs.team_minutes
        for_, against = (theirs.team_total("Shots · All", side=FOR),
                         theirs.team_total("Shots · All", side=AGAINST))
        print(f"   {label:15s} {minutes:6.1f} min of hockey   "
              f"shots {for_:4.0f} for / {against:4.0f} against   "
              f"per 60 {for_ / (minutes / 60) if minutes else 0:5.1f} / "
              f"{against / (minutes / 60) if minutes else 0:5.1f}")

    # ---------------------------------------------------------------- 7
    _rule(7, "CHECK IT  (a cube that disagreed with the reports is worthless)")
    wanted = [int(p) for p in summary.index[:5]]
    rows, _ = player_rows(conn, wanted, columns=SHOOTING, context=EVEN_STRENGTH,
                          stage=None, games=cube.games)
    report = {(row.player_id, column.key): row.totals[column.key]
              for row in rows for column in SHOOTING}
    even_strength = cube.slice_context(EVEN_STRENGTH)

    comparison = []
    for row in rows:
        his = even_strength.slice(players=[row.player_id])
        for column in SHOOTING:
            lane, side = column.lanes[0], column.side
            mine = his.total(lane, side=side,
                             value="xg" if column.weight else "n")
            theirs = report[(row.player_id, column.key)]
            comparison.append((cube.names.get(row.player_id, row.player_id),
                               f"{lane} ({side})", theirs, mine, mine - theirs))
    checked = pd.DataFrame(comparison, columns=["player", "column",
                                                "player_rows", "cube", "diff"])
    print(checked.head(12).to_string(index=False, float_format="%.2f"))
    worst = checked["diff"].abs().max()
    print(f"\n{len(checked)} figures compared against player_rows, "
          f"largest difference {worst:.4f}")

    # The same check for the other attribution, against team_rows -- which
    # also divides by game time, so this tests the new denominator too.
    reported = team_rows(conn, columns=SHOOTING, context=EVEN_STRENGTH,
                         stage=None, games=cube.games)
    team_slice = cube.slice_context(EVEN_STRENGTH)
    team_check = []
    for row in reported:
        mine = team_slice.slice(teams=[row.team_id])
        team_check.append((row.name, "TOI (min)", row.minutes,
                           mine.team_minutes, mine.team_minutes - row.minutes))
        for column in SHOOTING:
            value = mine.team_total(column.lanes[0], side=column.side,
                                    value="xg" if column.weight else "n")
            theirs = row.totals[column.key]
            team_check.append((row.name, f"{column.lanes[0]} ({column.side})",
                               theirs, value, value - theirs))
    team_frame = pd.DataFrame(team_check, columns=["team", "column", "team_rows",
                                                   "cube", "diff"])
    print(f"\n{team_frame.head(7).to_string(index=False, float_format='%.2f')}")
    team_worst = team_frame["diff"].abs().max()
    print(f"\n{len(team_frame)} figures compared against team_rows across "
          f"{len(reported)} teams, largest difference {team_worst:.4f}")
    worst = max(worst, team_worst)
    # Counts are exact. xG is stored rounded to four decimals, so a season's
    # worth of shots can drift a thousandth of a goal; the threshold allows
    # that and nothing more.
    print("AGREES" if worst < 0.005 else ">>> DISAGREES -- do not trust the cube <<<")

    conn.close()


if __name__ == "__main__":
    main()
