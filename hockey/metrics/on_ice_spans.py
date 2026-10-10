#!/usr/bin/python
"""What situation was it, from each bench's side.

Two questions have to be answered before any on-ice number exists, and
neither is a metric. One of them now lives a layer down:

* ``model/toi.skater_spans`` -- the merged intervals each skater was on the
  ice for. It was here until ``derive/lines.py`` needed the same spans, which
  ``metrics/`` cannot be imported from; it reads only a ``ToIInterval`` and a
  ``Roster``, so the model is where it belongs. Import it from there.
* :class:`SituationTimeline` -- the game cut into stretches of constant
  situation, each stretch labelled from BOTH teams' points of view. That one
  stays: it is the only thing here that reads ``context_filter``.

They were written for ``skater.py``'s goals-for/against and now also serve
``woi.py``, which asks them of every shot rather than of the half-dozen goals
in a game. That change of scale is why this module exists separately and why
the timeline is indexed rather than scanned:

* it is built with a difference array over the cut points instead of
  re-counting every shift at every cut -- O(shifts log cuts) rather than
  O(shifts x cuts), which on a 410-game season is the difference between
  minutes and seconds;
* :meth:`SituationTimeline.at` bisects, so classifying an event costs a
  lookup and not a walk.

It produces exactly what the straightforward loop produced -- verified
against ``skater.py``'s own checks: the manpower partition still sums to each
skater's total TOI, and the file and database paths still agree field for
field on every skater.

GOALIES ARE NOT SKATERS, but they are not absent either. ``skater_spans``
drops them, because a goalie is not a line to be credited; the timeline keeps
them, because a pulled goalie is what separates 6v5 from a power play.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence

from hockey.model.roster import GOALIE, Roster
from hockey.model.toi import Span, ToIInterval
from hockey.derive import context_filter as ctx

#: ``(period, manpower, goalies)`` -- one team's view of one moment.
Situation = tuple[str, str, str]


def on_ice_at(spans: Sequence[Span], t: float) -> bool:
    """Whether ``t`` falls inside one of the (sorted, disjoint) spans."""
    i = bisect_right(spans, (t, float("inf")))
    return i > 0 and spans[i - 1][0] <= t < spans[i - 1][1]


class SituationTimeline:
    """One game cut into stretches of constant situation.

    Each stretch is ``(start, end, {team_id: (period, manpower, goalies)})``,
    every team's situation stated from ITS OWN side -- so one stretch reads PP1
    for one bench and SH1 for the other. Anything crediting both teams has to
    ask per team rather than once.

    The cuts are every shift start and end, plus the period boundaries: between
    two consecutive cuts nobody steps on or off, so the situation holds across
    the whole stretch and can be credited in one go. Period boundaries join the
    list defensively -- no shift straddles one in the games checked, but a
    stretch spanning two periods would otherwise be credited entirely to one of
    them.

    A stretch with only one team on the ice is a gap in the data, not a 5v0,
    and is dropped: strength is a comparison and it takes two teams.
    """

    __slots__ = ("slices", "_starts")

    def __init__(self, toi: Sequence[ToIInterval], roster: Roster) -> None:
        self.slices = _build_slices(toi, roster)
        self._starts = [lo for lo, _, _ in self.slices]

    def __len__(self) -> int:
        return len(self.slices)

    def at(self, t: float) -> dict[int, Situation] | None:
        """Both teams' situations at ``t``, or None outside play.

        Bisected rather than scanned: a season's worth of shots asked of a
        timeline with ~800 stretches is the one place this gets hot.
        """
        i = bisect_right(self._starts, t) - 1
        if i < 0:
            return None
        lo, hi, situations = self.slices[i]
        return situations if lo <= t < hi else None

    def situation_at(self, t: float, team_id: int) -> Situation | None:
        """The situation at ``t`` from ``team_id``'s side, or None."""
        situations = self.at(t)
        return None if situations is None else situations.get(team_id)

    def selected_seconds(self, spans: Sequence[Span], team_id: int | None,
                         context) -> float:
        """Seconds on the ice with this player's team's situation selected.

        The TOI denominator that matches a narrowed count: pass the same
        ``ContextFilter`` used on the events and a per-60 rate divides like
        with like -- power-play goals over power-play minutes.
        """
        if team_id is None or not self.slices:
            return 0.0
        total = 0.0
        for start, end in spans:
            i = max(bisect_right(self._starts, start) - 1, 0)
            while i < len(self.slices) and self.slices[i][0] < end:
                lo, hi, situations = self.slices[i]
                i += 1
                overlap = min(hi, end) - max(lo, start)
                if overlap <= 0:
                    continue
                situation = situations.get(team_id)
                if situation is None:
                    continue
                if context.matches_situation(team_id=team_id,
                                             period=situation[0],
                                             manpower=situation[1],
                                             goalies=situation[2]):
                    total += overlap
        return total


def _build_slices(toi: Sequence[ToIInterval],
                  roster: Roster) -> list[tuple[float, float, dict[int, Situation]]]:
    """The cutting itself. See :class:`SituationTimeline` for what it means.

    Counting is a difference array over the cut points: a shift covers a
    contiguous run of them, so it contributes +1 at the cut it starts on and -1
    at the cut it ends on, and one prefix sum gives every stretch's skater
    count. The obvious alternative -- re-counting every shift at every cut --
    is quadratic in a game's shifts and dominates a season-sized run.
    """
    end_of_game = max((x.end_t for x in toi if x.end_t is not None), default=0.0)
    spans = [(x.start_t, end_of_game if x.end_t is None else x.end_t,
              x.player_id, x.team_id) for x in toi]

    cuts = {a for a, _, _, _ in spans} | {b for _, b, _, _ in spans}
    cuts |= {n * ctx.PERIOD_LENGTH
             for n in range(1, int(end_of_game // ctx.PERIOD_LENGTH) + 1)
             if 0 < n * ctx.PERIOD_LENGTH < end_of_game}
    cut_list = sorted(cuts)
    stretches = len(cut_list) - 1
    if stretches < 1:
        return []

    teams = sorted({team_id for _, _, _, team_id in spans if team_id is not None})
    skater_delta = {team_id: [0] * (stretches + 1) for team_id in teams}
    goalie_delta = {team_id: [0] * (stretches + 1) for team_id in teams}

    for start, end, player_id, team_id in spans:
        if team_id is None:
            continue
        first = bisect_left(cut_list, start)
        last = bisect_left(cut_list, end)
        if last <= first:
            continue
        player = roster.players.get(player_id)
        delta = (goalie_delta if player is not None and player.position == GOALIE
                 else skater_delta)[team_id]
        delta[first] += 1
        delta[last] -= 1

    out: list[tuple[float, float, dict[int, Situation]]] = []
    running_skaters = dict.fromkeys(teams, 0)
    running_goalies = dict.fromkeys(teams, 0)
    for index in range(stretches):
        for team_id in teams:
            running_skaters[team_id] += skater_delta[team_id][index]
            running_goalies[team_id] += goalie_delta[team_id][index]
        present = [team_id for team_id in teams
                   if running_skaters[team_id] or running_goalies[team_id]]
        if len(present) != 2:
            continue
        lo, hi = cut_list[index], cut_list[index + 1]
        if hi <= lo:
            continue
        period = ctx.period_from_time(lo)
        first, second = present
        situations = {
            own: (period,
                  ctx.manpower_from_skaters(
                      running_skaters[own], running_skaters[other],
                      own_goalie_on=bool(running_goalies[own]),
                      opposing_goalie_on=bool(running_goalies[other])),
                  ctx.goalies_from_flags(bool(running_goalies[own]),
                                         bool(running_goalies[other])))
            for own, other in ((first, second), (second, first))
        }
        out.append((lo, hi, situations))
    return out
