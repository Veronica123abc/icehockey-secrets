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
never asks how they were obtained. :func:`from_games` adapts built ``Game``
objects; a database adapter reading `event`, `shift` and `affiliation` in bulk
would yield the same bundles, which matters because building a game costs
~0.9s and ~23MB, so a 52-game season is ~48s and ~1.2GB the slow way.

AND IT CONSUMES THEM ONE AT A TIME. That is deliberate, not incidental. The
bulk of a game's 23MB is the supplier payload hanging off its events, so
flattening a season into one list of events would hold all of it at once and
undo the saving. Totals are accumulated per game and the game is then dropped.

Measured, because "streaming saves memory" is the kind of claim that is easy
to assert and easy to get wrong: peak is flat at ~73MB across 2, 4, 6, 8 and
10 games -- it does not grow with the number of games, so a 52-game season
costs the same as a two-game one. Materialising the same six games instead
peaked at 162MB and would scale from there. The accumulator itself is noise
(213 players ~ 0.04MB), and releasing the loop variable early changes nothing,
so the bound really is "about one game" rather than "one game per something".

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

GAME CONTEXT IS IGNORED FOR NOW. Every event in the games counts, whatever the
manpower or period. :func:`skater_stats` takes a ``context`` argument for when
that changes: pass a ``hockey.derive.context_filter.ContextFilter`` and the
events would be narrowed before anything is counted. Note that TOI would then
also need narrowing to match -- time on ice is an interval problem, not an
event one -- so the argument is deliberately left at "no filtering" until both
halves can be done together.

TWO THINGS ABOUT AGGREGATING ACROSS GAMES. A player's id is stable across
games in a league (20 of the 42 skaters in game 186461 also play 186449), so
totals add up cleanly. But a player can appear for more than one team across a
list, so ``team_id`` on a line is the team he played most games for, not a
fact about every game.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, fields

from hockey.model.events import Event
from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval
from hockey.derive.scoring import scoring
from hockey.derive.shooting import metrics as shooting

#: Roster position marking a goalie.
GOALIE = "G"

#: The counted metrics, in report order. games_played and the TOI columns
#: describe the sample rather than counting events, so they are not here.
METRICS = ("goals", "assists", "shot_attempts", "shots_on_net",
           "goals_for_woi", "goals_against_woi")


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


# --- On-ice spans -----------------------------------------------------------

def _skater_spans(toi: Sequence[ToIInterval],
                  roster: Roster) -> dict[int, list[tuple[float, float]]]:
    """player id -> his on-ice spans in this game, merged and sorted.

    Goalies are dropped. ``end_t`` is None when the supplier never recorded the
    player coming off; it does not happen in the games checked, but the model
    allows it, so an open shift is closed at the last time anything ends rather
    than running to infinity.

    Merging is defensive: no player's intervals overlap in the games checked,
    but a double-counted second would quietly inflate TOI if that changed.
    """
    end_of_game = max((x.end_t for x in toi if x.end_t is not None), default=0.0)
    raw: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for interval in toi:
        player = roster.players.get(interval.player_id)
        if player is not None and player.position == GOALIE:
            continue
        end = end_of_game if interval.end_t is None else interval.end_t
        if end > interval.start_t:
            raw[interval.player_id].append((interval.start_t, end))

    merged: dict[int, list[tuple[float, float]]] = {}
    for player_id, spans in raw.items():
        spans.sort()
        out = [spans[0]]
        for start, end in spans[1:]:
            if start <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], end))
            else:
                out.append((start, end))
        merged[player_id] = out
    return merged


def _on_ice_at(spans: Sequence[tuple[float, float]], t: float) -> bool:
    """Whether ``t`` falls inside one of the (sorted, disjoint) spans."""
    i = bisect_right(spans, (t, float("inf")))
    return i > 0 and spans[i - 1][0] <= t < spans[i - 1][1]


# --- Accumulating one game at a time ----------------------------------------

class _Totals:
    """Running totals across games. One game is added, then dropped."""

    def __init__(self) -> None:
        self.tally: dict[int, dict[str, float]] = defaultdict(
            lambda: dict.fromkeys(("toi",) + METRICS, 0))
        self.teams: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.names: dict[int, tuple[str, str]] = {}
        self.games_seen: dict[int, set[int]] = defaultdict(set)

    def add(self, data: GameData) -> None:
        spans = _skater_spans(data.toi, data.roster)

        for player_id, player_spans in spans.items():
            self.games_seen[player_id].add(data.game_id)
            self.tally[player_id]["toi"] += sum(end - start
                                                for start, end in player_spans)
            player = data.roster.players.get(player_id)
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
                if event.player_id is not None and event.player_id in spans:
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
                if not (_on_ice_at(player_spans, goal.t)
                        or goal.player_id == player_id):
                    continue
                player = data.roster.players.get(player_id)
                if player is None or player.team_id is None:
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

    ``context`` is accepted and must be None for now: filtering events by
    manpower or period without also narrowing TOI would rate a full game's
    events against a partial denominator. See the module docstring.
    """
    if context is not None:
        raise NotImplementedError(
            "context filtering needs TOI narrowed to the same situation; "
            "see the module docstring")

    totals = _Totals()
    for data in games:
        totals.add(data)
    return totals.lines(min_toi)


# --- Adapters ---------------------------------------------------------------

def from_games(games: Iterable) -> Iterator[GameData]:
    """Adapt built ``Game`` objects. Lazy, so the games stream."""
    for game in games:
        yield GameData.from_game(game)


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


def to_dataframe(lines: Iterable[SkaterLine]):
    """The lines as a DataFrame. pandas is imported here so the module stays
    usable without it."""
    import pandas as pd
    columns = [f.name for f in fields(SkaterLine)]
    return pd.DataFrame([[getattr(line, c) for c in columns] for line in lines],
                        columns=columns)


def print_lines(lines: Sequence[SkaterLine], *, limit: int | None = None) -> None:
    """A plain table, for a terminal or an IDE run window."""
    header = (f"{'player':22s} {'pos':3s} {'GP':>3s} {'TOI':>7s} {'TOI/GP':>7s} "
              f"{'G':>4s} {'A':>4s} {'SA':>4s} {'SOG':>4s} {'GF/oi':>6s} {'GA/oi':>6s}")
    print(header)
    print("-" * len(header))
    for line in lines[:limit]:
        print(f"{line.name[:22]:22s} {line.position:3s} {line.games_played:3d} "
              f"{line.toi:7.1f} {line.toi_per_game:7.1f} "
              f"{line.goals:4d} {line.assists:4d} {line.shot_attempts:4d} "
              f"{line.shots_on_net:4d} {line.goals_for_woi:6d} {line.goals_against_woi:6d}")


if __name__ == "__main__":
    GAME_IDS = [186449, 186461]

    lines = skater_stats(from_games(load_games(GAME_IDS)))
    print(f"{len(lines)} skaters over {len(GAME_IDS)} games\n")
    print_lines(lines, limit=25)

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
