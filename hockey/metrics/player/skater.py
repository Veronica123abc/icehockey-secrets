#!/usr/bin/python
"""Skater box scores over a set of games.

The same numbers the game canvas puts in its player report, as a function you
can call without the GUI::

    from hockey.metrics.player.skater import (skater_stats, from_games,
                                              load_games, print_lines)

    lines = skater_stats(from_games(load_games([186449, 186461])))
    print_lines(lines, limit=20)

One line per skater who appears in any of the games, aggregated across all of
them.

METRICS COME FROM ``hockey/derive/``, NOT FROM HERE. Goals and assists are
``scoring.all_goals`` / ``all_assists``; shot attempts are
``shooting.all_shots``; shots on net is ``shooting.filter_shots(shots,
Result=['On Net'])`` -- the same predicate the canvas rail ticks. This module
decides only who to credit and how to add things up, so a change to what "on
net" means happens in one place and arrives here for free.

WHERE THE DATA COMES FROM IS NOT THIS MODULE'S BUSINESS. :func:`skater_stats`
consumes :class:`GameData` -- the events, shifts and roster of one game -- and
never asks how they were obtained. Two adapters produce them:

* :func:`from_games` adapts built ``Game`` objects, from files or anywhere.
* :func:`from_database` reads `event`, `shift` and `affiliation` in bulk.

The second exists because building games does not scale: ~0.9s and ~23MB each,
so a 52-game season is ~48s and holds a payload it never looks at. The query
path asks only for the event names the metrics actually read -- 2521 rows for
twenty games, 0.41s against ~18s. Measured on a real season rather than
extrapolated: 410 games, 431 skaters, 17.6s.

GAMES THAT ARE NOT INGESTED ARE SKIPPED, AND SAID SO. :func:`from_database`
warns naming them rather than falling back to files, because a silent fallback
would make a season's numbers depend on which machine ran it and on which
games happened to be on that disk. :func:`available_games` answers the same
question directly if you would rather check first. A game counts as usable
only with BOTH events and shifts: events alone would produce a full set of
counts against no ice time, which is worse than skipping it.

AND IT CONSUMES THEM ONE AT A TIME. That is deliberate, not incidental. The
bulk of a game's 23MB is the supplier payload hanging off its events, so
flattening a season into one list of events would hold all of it at once and
undo the saving. Totals are accumulated per game and the game is then dropped.

Measured ON THE FILE PATH, because "streaming saves memory" is the kind of
claim that is easy to assert and easy to get wrong: peak is flat at ~73MB
across 2, 4, 6, 8 and 10 games -- it does not grow with the number of games,
so a 52-game season costs the same as a two-game one. Materialising the same
six games instead peaked at 162MB and would scale from there. The accumulator
itself is noise (213 players ~ 0.04MB), and releasing the loop variable early
changes nothing, so the bound really is "about one game" rather than "one game
per something".

THE DATABASE PATH DOES NOT STREAM, and that flat bound is not its bound.
:func:`_database_bundles` runs its queries and buffers every game's events,
shifts and roster before it yields the first bundle, so its peak scales with
the season instead of staying flat: 365MB over 410 games, against 85MB before
the call. :func:`skater_stats` still consumes one bundle at a time either way
-- it is the PRODUCING that is eager here, not the consuming. Worth knowing
before pointing it at something much larger than one season.

Pass a generator -- ``load_games`` is one -- rather than a list.

WHAT "WOI" MEANS. *With on ice*: goals scored by either team while the player
was on the ice, split by whether it was his team that scored. That is the
canvas's "Player WOI" mode, and it is computed the same way -- a player is
credited if the goal falls inside one of his shifts, OR if the goal is his
own. The second half is not redundant: about 2% of events (mostly faceoffs,
and occasionally a goal) sit a second or two outside the supplier's own shift
interval, and without it a player's own goal could be missing from his on-ice
count, leaving WOI not a superset of what he is credited with.

GOALIES ARE NOT SKATERS. This is ``skater.py``: goalies are dropped from the
output and from on-ice attribution. They are in the shift data -- seven or
eight intervals a game -- so they have to be dropped explicitly rather than
assumed absent.

GAME CONTEXT NARROWS BOTH HALVES. Pass a ``ContextFilter`` as ``context`` and
the counts drop to events in that situation AND the TOI denominator drops to
time spent in it, so a per-60 rate divides like with like::

    pp = ctx.DEFAULT.with_values(ctx.MANPOWER, [ctx.PP1])
    lines = skater_stats(from_games(load_games(ids)), context=pp, min_toi=20)
    print_lines(lines, per60=True)      # PP goals over PP minutes

RATES ARE DERIVED, NOT STORED. ``SkaterLine.per60(metric)`` divides the count
by that line's own TOI, so it cannot fall out of step with either, and under a
context it is automatically the narrowed denominator -- that is the whole point
of narrowing both halves. ``min_toi`` is what keeps a rate honest: four
power-play minutes and one goal is 15.0 G/60, arithmetically correct and
worthless. Nothing here enforces a floor, because what counts as enough sample
depends on the question.

EVERYTHING IS RELATIVE TO THE PLAYER'S OWN TEAM, which is the subtle part. A
goal scored by team A on the power play is PP1 from A's side and SH1 for a
team B skater who was on the ice for it. So WOI cannot simply ask whether the
GOAL is selected -- it asks whether the goal's moment is selected from each
credited player's side, which is the opposite answer on the two benches.

TOI IS NOT AN EVENT, SO IT IS SWEPT. A shift carries no period, manpower or
goalie field, and the situation changes whenever anyone steps on or off. The
shifts of a game are cut at every boundary, each slice is classified from each
team's side by ``context_filter``'s situation rules, and a skater is credited
the slices his team's situation is selected for. Period boundaries join the
cut list defensively: no shift straddles one in the games checked, but a slice
spanning two periods would otherwise be credited entirely to one of them.

That sweep is :mod:`hockey.metrics.player.on_ice_spans`, not this file --
``woi.py`` asks the same two questions of every shot in a season, and one
implementation of "who was on, in what situation" is the whole point.

Numerator and denominator classify by slightly different means, deliberately.
An event carries the supplier's own ``manpower_situation`` and uses it; a slice
has to derive direction from the skater counts. The two agree in sign on 99.69%
of compiled events, so they part company only over a few empty-net seconds.

TWO THINGS ABOUT AGGREGATING ACROSS GAMES. A player's id is stable across
games in a league (20 of the 42 skaters in game 186461 also play 186449), so
totals add up cleanly. But a player can appear for more than one team across a
list, so ``team_id`` on a line is the team he played most games for, not a
fact about every game.
"""
from __future__ import annotations

import warnings
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, fields

from hockey.model.events import Event
from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval
from hockey.derive import context_filter as ctx
from hockey.derive.scoring import scoring
from hockey.derive.shooting import metrics as shooting
from hockey.metrics.player.on_ice_spans import (GOALIE, SituationTimeline,
                                                on_ice_at, skater_spans)

#: The counted metrics, in report order. games_played and the TOI columns
#: describe the sample rather than counting events, so they are not here.
METRICS = ("goals", "assists", "shot_attempts", "shots_on_net",
           "goals_for_woi", "goals_against_woi")

#: One report column per metric: field name, count heading, rate heading. The
#: table is built from this rather than from a hand-written header string, so a
#: metric added to METRICS cannot end up with its numbers under the wrong name.
_METRIC_COLUMNS = (
    ("goals",             "G",     "G/60"),
    ("assists",           "A",     "A/60"),
    ("shot_attempts",     "SA",    "SA/60"),
    ("shots_on_net",      "SOG",   "SOG/60"),
    ("goals_for_woi",     "GF/oi", "GF/60"),
    ("goals_against_woi", "GA/oi", "GA/60"),
)

#: The supplier event names :meth:`_Totals.add` reads. The database adapter
#: asks for these and no others, which is most of why it is quick -- but it
#: means adding a metric over a new event name means adding the name here too,
#: or the query path will quietly under-report what the file path finds.
EVENT_NAMES = ("goal", "assist", "shot")


@dataclass(frozen=True)
class GameData:
    """One game's events, shifts and roster -- whatever produced them.

    This is the seam between "where the data comes from" and "what the numbers
    are". A ``Game`` built from JSON, a ``Game`` built from the database, or
    three bulk queries grouped by game all reduce to this.

    It deliberately exposes ``events`` under that name, because the base-set
    helpers in ``hockey/derive`` read exactly that attribute and nothing else
    -- ``scoring.all_goals(data)`` works, so the population definitions stay
    in the metric modules rather than being restated here.
    """
    game_id: int
    events: Sequence[Event]
    toi: Sequence[ToIInterval]
    roster: Roster

    @classmethod
    def from_game(cls, game) -> "GameData":
        return cls(game_id=game.game_id, events=game.events,
                   toi=game.toi, roster=game.roster)


@dataclass(frozen=True, slots=True)
class SkaterLine:
    """One skater's totals across the games given. Ids are SportLogIQ ids."""
    player_id: int
    name: str
    team_id: int
    position: str
    games_played: int
    toi: float                  # minutes, summed over the games
    toi_per_game: float         # minutes
    goals: int
    assists: int
    shot_attempts: int
    shots_on_net: int
    goals_for_woi: int          # goals by his team while he was on the ice
    goals_against_woi: int      # goals against his team while he was on the ice

    def per60(self, metric: str) -> float:
        """One metric as a rate per 60 minutes of ice time.

        Derived rather than stored: the count and the TOI are both already on
        the line, and a stored rate would be a third number to keep in step.

        The denominator is THIS LINE's TOI, which is what makes the rate safe
        under a context: ``skater_stats`` narrows the events and the ice time
        together, so a power-play line's G/60 is power-play goals over
        power-play minutes, never over whole games. It is also why a rate is
        only as trustworthy as the sample behind it -- use ``min_toi`` to keep
        four power-play minutes from reporting 15.0 G/60.
        """
        if metric not in METRICS:
            raise KeyError(f"unknown metric {metric!r}; metrics are {METRICS}")
        return getattr(self, metric) * 60.0 / self.toi if self.toi else 0.0


# --- Accumulating one game at a time ----------------------------------------

class _Totals:
    """Running totals across games. One game is added, then dropped."""

    def __init__(self) -> None:
        self.tally: dict[int, dict[str, float]] = defaultdict(
            lambda: dict.fromkeys(("toi",) + METRICS, 0))
        self.teams: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.names: dict[int, tuple[str, str]] = {}
        self.games_seen: dict[int, set[int]] = defaultdict(set)

    def add(self, data: GameData, context=None) -> None:
        spans = skater_spans(data.toi, data.roster)
        timeline = (SituationTimeline(data.toi, data.roster)
                    if context is not None else None)

        for player_id, player_spans in spans.items():
            player = data.roster.players.get(player_id)
            if timeline is None:
                seconds = sum(end - start for start, end in player_spans)
            else:
                seconds = timeline.selected_seconds(
                    player_spans,
                    player.team_id if player is not None else None, context)
                if seconds <= 0:
                    # On the ice, but never in the selected situation. Counting
                    # the game would inflate games_played and deflate TOI/GP.
                    continue
            self.games_seen[player_id].add(data.game_id)
            self.tally[player_id]["toi"] += seconds
            if player is not None:
                if player.team_id is not None:
                    self.teams[player_id][player.team_id] += 1
                first = (player.first_name or "").strip()
                last = (player.last_name or "").strip()
                self.names[player_id] = (
                    " ".join(p for p in (first, last) if p) or str(player_id),
                    player.position or "")

        def credit(events: Iterable[Event], metric: str) -> None:
            for event in events:
                if event.player_id is None or event.player_id not in spans:
                    continue
                # An event credited to a player belongs to his team, so the
                # supplier's classification is already from his side.
                if context is not None and not context.matches(event):
                    continue
                self.tally[event.player_id][metric] += 1

        # The derive helpers read only `.events`, which GameData provides.
        shots = shooting.all_shots(data)
        credit(scoring.all_goals(data), "goals")
        credit(scoring.all_assists(data), "assists")
        credit(shots, "shot_attempts")
        credit(shooting.filter_shots(shots, Result=["On Net"]), "shots_on_net")

        # WOI: every goal counts for every skater on the ice for it, whichever
        # team scored. A player's own goal counts even if it sits just outside
        # his recorded shift -- see the module docstring.
        for goal in scoring.all_goals(data):
            if goal.t is None or goal.team_id is None:
                continue
            for player_id, player_spans in spans.items():
                if not (on_ice_at(player_spans, goal.t)
                        or goal.player_id == player_id):
                    continue
                player = data.roster.players.get(player_id)
                if player is None or player.team_id is None:
                    continue
                if context is not None:
                    # Asked from HIS side, not the scorer's: a power-play goal
                    # against is a penalty kill for the man on the ice.
                    situation = timeline.situation_at(goal.t, player.team_id)
                    if situation is None or not context.matches_situation(
                            team_id=player.team_id, period=situation[0],
                            manpower=situation[1], goalies=situation[2]):
                        continue
                metric = ("goals_for_woi" if player.team_id == goal.team_id
                          else "goals_against_woi")
                self.tally[player_id][metric] += 1

    def lines(self, min_toi: float) -> list[SkaterLine]:
        out: list[SkaterLine] = []
        for player_id, counts in self.tally.items():
            minutes = counts["toi"] / 60.0
            if minutes <= min_toi:
                continue
            played = len(self.games_seen[player_id])
            name, position = self.names.get(player_id, (str(player_id), ""))
            team_id = (max(self.teams[player_id].items(), key=lambda kv: kv[1])[0]
                       if self.teams[player_id] else 0)
            out.append(SkaterLine(
                player_id=player_id,
                name=name,
                team_id=team_id,
                position=position,
                games_played=played,
                toi=minutes,
                toi_per_game=minutes / played if played else 0.0,
                **{metric: int(counts[metric]) for metric in METRICS},
            ))
        out.sort(key=lambda line: line.toi, reverse=True)
        return out


# --- The public function ----------------------------------------------------

def skater_stats(games: Iterable[GameData], *, min_toi: float = 0.0,
                 context=None) -> list[SkaterLine]:
    """One line per skater appearing in ``games``, sorted by TOI descending.

    ``games`` is an iterable of :class:`GameData`; pass a generator and only
    one game is held at a time. ``min_toi`` is in minutes, across all of them.

    ``context`` is a ``hockey.derive.context_filter.ContextFilter``. It narrows
    the events counted AND the ice time they are counted over, so the two
    halves describe the same situation -- ``min_toi`` is then minutes in that
    situation, not minutes of hockey.
    """
    totals = _Totals()
    for data in games:
        totals.add(data, context)
    return totals.lines(min_toi)


# --- Adapters ---------------------------------------------------------------

def from_games(games: Iterable) -> Iterator[GameData]:
    """Adapt built ``Game`` objects. Lazy, so the games stream."""
    for game in games:
        yield GameData.from_game(game)


def available_games(conn, game_sl_ids: Iterable[int]) -> tuple[list[int], list[int]]:
    """``(usable, missing)`` for the ids asked for, in the order given.

    Usable means the database holds BOTH events and shifts for the game. A
    game row on its own is not enough: counts with no ice time behind them
    would look like a very idle player rather than like missing data.
    """
    game_sl_ids = list(dict.fromkeys(game_sl_ids))
    if not game_sl_ids:
        return [], []
    placeholders = ", ".join(["%s"] * len(game_sl_ids))
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""SELECT g.sl_id,
                       EXISTS(SELECT 1 FROM event e WHERE e.game_id = g.id),
                       EXISTS(SELECT 1 FROM shift s WHERE s.game_id = g.id)
                FROM game g WHERE g.sl_id IN ({placeholders})""",
            tuple(game_sl_ids))
        complete = {int(sl) for sl, has_events, has_shifts in cursor.fetchall()
                    if has_events and has_shifts}
    finally:
        cursor.close()
    usable = [g for g in game_sl_ids if g in complete]
    missing = [g for g in game_sl_ids if g not in complete]
    return usable, missing


def from_database(conn, game_sl_ids: Iterable[int], *,
                  names: Sequence[str] = EVENT_NAMES) -> Iterator[GameData]:
    """Bundles read straight from the database, in bulk rather than per game.

    The whole set costs ``6 + ceil(total_events / 5000)`` statements: one
    availability check, one for the events, two id maps, one per 5000-event
    chunk of `event_flag` (``_CHUNK`` in hockey/db/event_query.py), then one
    each for shifts and affiliation. Seven for eight games, sixteen for a
    410-game season. So it grows with event VOLUME rather than with the number
    of games -- but it does grow, and calling it a fixed number would be
    wrong; the point is that nothing here is per game.

    Games the database does not hold are skipped and named in a warning --
    see the module docstring for why they are not quietly read from files.

    Deliberately NOT a generator. Which games are missing is settled when you
    call this, not when something first iterates it, so the warning names the
    caller who passed the ids rather than whatever loop happened to consume
    them -- and it arrives even if the result is never iterated at all. The
    reading is still deferred to first iteration; it is the checking that is
    eager. Deferred is not incremental, though: once iteration does start,
    every query runs before the first bundle comes back, so the memory note in
    the module docstring applies from that point on.
    """
    usable, missing = available_games(conn, game_sl_ids)
    if missing:
        warnings.warn(
            f"{len(missing)} game(s) not in the database, skipped: "
            f"{', '.join(str(g) for g in missing)}",
            stacklevel=2)
    return _database_bundles(conn, usable, names)


def _database_bundles(conn, usable: Sequence[int],
                      names: Sequence[str]) -> Iterator[GameData]:
    """The reading half of :func:`from_database`, once the ids are settled.

    ``query_events`` and ``query_shifts`` are imported here rather than at the
    top because ``hockey.db.event_query`` resolves Settings at import time, and
    this module is meant to stay importable without DATA_ROOT_DIR.
    ``shift_query`` has no such problem; it is imported alongside for symmetry.
    """
    if not usable:
        return
    from hockey.db.event_query import query_events
    from hockey.db.roster_query import query_rosters
    from hockey.db.shift_query import query_shifts

    events_by_game: dict[int, list[Event]] = defaultdict(list)
    for event in query_events(conn, game_sl_ids=usable, names=list(names)):
        events_by_game[event.game_id].append(event)

    # Shifts come back already in SportLogIQ ids -- the space the events, the
    # roster and GameData.game_id all speak -- so grouping them is all that is
    # left to do here. Goalies are kept: _skater_spans drops them by roster,
    # and _situation_timeline needs them to tell a pulled goalie from a
    # penalty.
    toi_by_game: dict[int, list[ToIInterval]] = defaultdict(list)
    for interval in query_shifts(conn, game_sl_ids=usable):
        toi_by_game[interval.game_id].append(interval)

    # The roster is the third bulk read, and it is `affiliation` rather than
    # either of the other two tables -- who was dressed, and as what.
    rosters = query_rosters(conn, game_sl_ids=usable)
    empty = Roster(game_id=0, players={})

    for game_sl in usable:
        yield GameData(
            game_id=game_sl,
            events=events_by_game.get(game_sl, []),
            toi=toi_by_game.get(game_sl, []),
            roster=rosters.get(game_sl, empty))


def load_games(game_ids: Iterable[int], *,
               playsequence_source: str = "playsequence_compiled") -> Iterator:
    """Build Games from the local data root, one at a time.

    A generator on purpose: a built game retains ~23MB, so materialising a
    52-game season would hold ~1.2GB for no reason. Consumed by
    :func:`from_games`, the peak stays at about one game.
    """
    from pathlib import Path
    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
    for game_id in game_ids:
        yield build_game(RawGame(game_id=game_id, root_dir=settings.data_root_dir,
                                 playsequence_source=playsequence_source))


def to_dataframe(lines: Iterable[SkaterLine], *, per60: bool = True):
    """The lines as a DataFrame. pandas is imported here so the module stays
    usable without it.

    ``per60`` appends a ``<metric>_per60`` column for each counted metric. A
    DataFrame has no width to run out of, so they are on by default -- unlike
    the printed table, which has to choose.
    """
    import pandas as pd
    lines = list(lines)
    columns = [f.name for f in fields(SkaterLine)]
    rows = [[getattr(line, c) for c in columns] for line in lines]
    if per60:
        columns += [f"{metric}_per60" for metric, _, _ in _METRIC_COLUMNS]
        for row, line in zip(rows, lines):
            row += [line.per60(metric) for metric, _, _ in _METRIC_COLUMNS]
    return pd.DataFrame(rows, columns=columns)


def print_lines(lines: Sequence[SkaterLine], *, limit: int | None = None,
                per60: bool = False) -> None:
    """A plain table, for a terminal or an IDE run window.

    ``per60`` SWAPS the counting columns for rates per 60 minutes rather than
    adding to them -- twelve numeric columns do not fit a terminal, and the
    sample size stays on the row either way, because GP and TOI do not move.
    """
    headings = [head for _, count_head, rate_head in _METRIC_COLUMNS
                for head in (rate_head if per60 else count_head,)]
    width = 6 if per60 else 5
    header = (f"{'player':22s} {'pos':3s} {'GP':>3s} {'TOI':>7s} {'TOI/GP':>7s} "
              + " ".join(f"{head:>{width}s}" for head in headings))
    print(header)
    print("-" * len(header))
    for line in lines[:limit]:
        if per60:
            cells = [f"{line.per60(metric):{width}.2f}"
                     for metric, _, _ in _METRIC_COLUMNS]
        else:
            cells = [f"{getattr(line, metric):{width}d}"
                     for metric, _, _ in _METRIC_COLUMNS]
        print(f"{line.name[:22]:22s} {line.position:3s} {line.games_played:3d} "
              f"{line.toi:7.1f} {line.toi_per_game:7.1f} " + " ".join(cells))


if __name__ == "__main__":
    GAME_IDS = [186449, 186461]

    from hockey.db.database import open_database_azure
    from hockey.db.event_query import query_events




    lines = skater_stats(from_games(load_games(GAME_IDS)))
    print(f"{len(lines)} skaters over {len(GAME_IDS)} games\n")
    print_lines(lines, limit=25)

    # The same lines as rates. Sorted by TOI still, so the rows line up with
    # the table above -- and with a min_toi, because two games is a small
    # sample and a fourth-liner's G/60 off six minutes is not a number.
    print(f"\nper 60 minutes (min 20 min of ice time):\n")
    print_lines(skater_stats(from_games(load_games(GAME_IDS)), min_toi=20.0),
                limit=25, per60=True)

    # The totals have to agree with the events themselves, so check rather
    # than trust. Re-loading is the point: nothing above is still in memory.
    totals = {"goals": 0, "assists": 0, "shots": 0}
    for game in load_games(GAME_IDS):
        totals["goals"] += len(scoring.all_goals(game))
        totals["assists"] += len(scoring.all_assists(game))
        totals["shots"] += len(shooting.all_shots(game))
    print(f"\n   goals   credited {sum(l.goals for l in lines):4d} "
          f"of {totals['goals']:4d} in the games")
    print(f"   assists credited {sum(l.assists for l in lines):4d} "
          f"of {totals['assists']:4d}")
    print(f"   shots   credited {sum(l.shot_attempts for l in lines):4d} "
          f"of {totals['shots']:4d}")
    print(f"   WOI goals for+against {sum(l.goals_for_woi + l.goals_against_woi for l in lines)} "
          f"(a goal counts once per skater on the ice, so ~10x the goal count)")

    # Context narrows the events AND the ice time they are counted over, so
    # these are not slices of the table above -- each has its own denominator.
    print("\n   context selections (events and TOI narrowed together):")
    selections = [
        ("even strength", ctx.DEFAULT),
        ("power play", ctx.DEFAULT.with_values(ctx.MANPOWER, [ctx.PP1, ctx.PP2])),
        ("penalty kill", ctx.DEFAULT.with_values(ctx.MANPOWER, [ctx.SH1, ctx.SH2])),
        ("third period", ctx.DEFAULT.with_values(ctx.PERIOD, [ctx.P3])),
    ]
    for label, selection in selections:
        picked = skater_stats(from_games(load_games(GAME_IDS)), context=selection)
        minutes = sum(l.toi for l in picked)
        goals = sum(l.goals for l in picked)
        print(f"      {label:14s} {len(picked):3d} skaters  {minutes:7.1f} player-min  "
              f"{goals:2d} goals   [{' · '.join(selection.describe())}]")

    # Every player's ice time has to land in exactly one manpower bucket, so
    # the five of them add back up to his total. Cheap to check, and the whole
    # correctness of a per-60 rate rests on it.
    full = {l.player_id: l.toi for l in lines}
    summed: dict[int, float] = {}
    for value in ctx.MANPOWERS:
        selection = ctx.ContextFilter(teams=None, periods=frozenset({ctx.ALL}),
                                      manpower=frozenset({value}),
                                      goalies=frozenset(ctx.GOALIE_SITUATIONS))
        for line in skater_stats(from_games(load_games(GAME_IDS)), context=selection):
            summed[line.player_id] = summed.get(line.player_id, 0.0) + line.toi
    off = [p for p in full if abs(full[p] - summed.get(p, 0.0)) > 1e-6]
    print(f"\n   ES+SH1+SH2+PP1+PP2 == total TOI for all {len(full)} skaters: {not off}")

    # THE OTHER ADAPTER. Everything above went through load_games, which
    # builds one game at a time -- ~0.9s and ~23MB each. from_database reads
    # the same events in a handful of bulk queries for the whole set, none of
    # them per game, which is the path a season-sized run wants; the per-game
    # loop at the end of _database_bundles groups rows that have already
    # arrived, it does not fetch. Shown side by side because the file path is
    # the only one demonstrated above, which makes the fast one easy to miss.
    #
    # Skipped rather than failed when there is no database to talk to: this
    # demo has to keep working on a machine that only has the data files.
    import time

    print("\n   the same games, read from the database instead:")
    try:
        from hockey.db.database import open_database_azure
        conn = open_database_azure()
    except Exception as exc:
        print(f"      no database available ({type(exc).__name__}), skipped")
    else:
        usable, absent = available_games(conn, GAME_IDS)
        if absent:
            print("      not ingested, so not comparable: "
                  f"{', '.join(str(g) for g in absent)}")
        if not usable:
            print("      none of these games are in the database")
        else:
            start = time.perf_counter()
            db_lines = skater_stats(from_database(conn, usable))
            db_secs = time.perf_counter() - start

            start = time.perf_counter()
            file_lines = skater_stats(from_games(load_games(usable)))
            file_secs = time.perf_counter() - start

            print(f"      database {db_secs:5.2f}s   files {file_secs:5.2f}s   "
                  f"({file_secs / db_secs:4.1f}x)   {len(db_lines)} skaters")

            # Both adapters feed the same GameData seam, so the lines have to
            # agree field for field. If they ever stop agreeing the two paths
            # have drifted, and a season's numbers would depend on which one
            # happened to run -- exactly what from_database refuses to hide.
            columns = [f.name for f in fields(SkaterLine)]
            by_id = {line.player_id: line for line in file_lines}
            differing: list[str] = []
            for line in db_lines:
                other = by_id.get(line.player_id)
                if other is None:
                    differing.append(f"{line.name}: absent from the file path")
                    continue
                for column in columns:
                    mine, theirs = getattr(line, column), getattr(other, column)
                    same = (abs(mine - theirs) <= 1e-6
                            if isinstance(mine, float) else mine == theirs)
                    if not same:
                        differing.append(f"{line.name}: {column} "
                                         f"{mine!r} vs {theirs!r}")
            agree = not differing and len(db_lines) == len(file_lines)
            print(f"      identical to the file path, field for field: {agree}")
            for note in differing[:5]:
                print(f"         {note}")
