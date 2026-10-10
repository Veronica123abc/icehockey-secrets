#!/usr/bin/python
"""Who was on the ice TOGETHER, and for how long.

A LINE COMBINATION is a set of skaters that shared the ice, with every stretch
they shared it for. Not a line as a coach writes it on a whiteboard -- those
are three forwards and two defencemen, planned -- but the unit that was
actually out there, however it came about: a planned unit, a unit missing a
man on a change, a power-play five, a penalty-killing four. One object per
distinct set, so the same five together in the first period and again in the
third are ONE combination with two spans, which is what makes a per-line
number possible in the first place.

This is the denominator layer for line metrics, and it is deliberately only
that: it answers who and when, never what they did. Crediting events to a
line is the next step and belongs on top of :func:`on_ice_stretches`.

WHY IT IS IN ``derive/`` WITHOUT BEING A METRIC MODULE. There is no population
of events here and no ``Event -> bool`` predicate, so there is no
``FilterGroups`` to bind, nothing to register in ``metric_catalog`` and no
lane key -- it is one of the things §1 of ``derive/CLAUDE.md`` calls
deliberately outside the pattern, like ``entries.py``'s ``ZoneEntry``. It
sweeps ``ToIInterval``s rather than filtering events, which is also why
``golden.py`` cannot protect it: that harness sweeps ``get_full_data`` and
hashes event identities, and there are no events to hash. The ``__main__``
block here is the substitute -- it re-checks the two invariants below on a
real game.

    python hockey/derive/lines.py

THE RULES, and the evidence for them. Measured over the golden twenty
(186449-186468, compiled playsequence), 40 team-games:

* **Half-open spans.** ``[start, end)``, and spans that touch are one span:
  a player who changes nothing but his shift record at 10:00 did not leave.
  Merging is ``toi.merge_spans``, as everywhere else.
* **Goalies are not skaters.** Dropped, so a combination is 3-6 players and a
  pulled goalie reads as the sixth skater he buys rather than as a seventh
  man. That is not decided here: the spans come from ``toi.skater_spans``,
  the one place that turns shift intervals into a skater's ice time, so a line
  is made of exactly the seconds a TOI denominator is made of. What this
  module adds is which bench each one belongs to
  (:func:`_team_of_player`) and the sweep below.
* **3 to 6 skaters.** Seconds by skater count over the twenty: 5 skaters
  127983s, 4 (a penalty) 14702s, 3 (two penalties) 2517s, 6 (goalie pulled)
  1448s -- and 55s with a single skater, which is a gap in the shift data
  rather than a unit on the ice (plus one second with nobody at all, which
  :func:`on_ice_stretches` does not return). So the clamp drops 0.037% of the
  ice time, and it drops it where the data has stopped describing a game.
* **A combination is as short as the ice says.** 132.7 distinct combinations
  per team-game (min 67, median 129, max 202), because every staggered change
  puts a transient set on the ice for a second or two. Those transients hold
  6.91% of all ice time, and only 66.1 combinations per team-game reach ten
  seconds (15.5 reach a minute). Nothing is dropped by default -- a
  one-second unit was really out there and a conceded goal would count --
  but ``min_seconds`` is there for the callers that want the units a coach
  would recognise.

Two invariants, checked by ``__main__`` on every game it is pointed at and
over the twenty while this was written:

* the spans of one combination never overlap (0 violations);
* **the combinations partition the ice time**: for every skater, the time he
  spends in combinations containing him equals his own on-ice time inside the
  3-6 clamp (0 mismatches over 40 team-games). A line table whose TOI column
  does not add up to the players' own TOI is measuring something else, and
  this is what says it does.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from hockey.model.roster import Roster
from hockey.model.toi import Span, ToIInterval, merge_spans, skater_spans

#: Three skaters is a double minor served; six is a pulled goalie. Outside
#: this the shift data has stopped describing a game -- see the module
#: docstring for what that costs (0.038% of the ice time).
MIN_SKATERS = 3
MAX_SKATERS = 6

#: One stretch of constant on-ice set: ``(start, end, players)``.
Stretch = tuple[float, float, frozenset[int]]


@dataclass(frozen=True, slots=True)
class LineCombination:
    """One set of skaters, and every stretch they were on the ice together.

    ``toi`` is a property rather than a field on purpose: a stored total and a
    list of spans are two statements of the same fact, and the one that can go
    stale is the total. Ask the spans.
    """

    team_id: int
    #: The skaters, sorted, so the tuple is a stable dict key for this unit.
    players: tuple[int, ...]
    #: Every stretch they shared the ice, sorted, half-open, non-overlapping.
    spans: tuple[Span, ...]

    @property
    def toi(self) -> float:
        """Seconds this unit spent on the ice together."""
        return sum(end - start for start, end in self.spans)

    @property
    def shifts(self) -> int:
        """How many separate stretches that time came in."""
        return len(self.spans)

    @property
    def size(self) -> int:
        """How many skaters -- 5 at full strength, 4 a man down, 6 pulled."""
        return len(self.players)


def _team_of_player(toi: Sequence[ToIInterval],
                    roster: Roster) -> dict[int, int]:
    """player id -> the team he played for in this game.

    Which bench a shift belongs to, which is the one thing a line combination
    needs that a span does not say. The shift itself answers it -- the
    supplier's own attribution -- and the roster answers only where the
    interval does not, which the model allows but which did not occur in any
    game checked (0 of 2428 intervals over three games, the two sources
    never disagreeing on the rest).

    The spans themselves are ``toi.skater_spans``: drop goalies, close an
    open shift, merge. That policy used to be written again here, which is
    why it is in the model now -- see its docstring.
    """
    out: dict[int, int] = {}
    for interval in toi:
        team_id = interval.team_id
        if team_id is None:
            player = roster.players.get(interval.player_id)
            team_id = None if player is None else player.team_id
        if team_id is not None:
            out.setdefault(interval.player_id, team_id)
    return out


def on_ice_stretches(data) -> dict[int, list[Stretch]]:
    """team id -> the game cut into stretches of constant on-ice skater set.

    ``data`` is anything carrying ``toi`` and ``roster``: a ``Game`` or a
    ``GameData`` bundle, so where the game came from is not this module's
    business.

    The cuts are every shift start and end for that team: between two
    consecutive cuts nobody steps on or off, so the set holds across the whole
    stretch. Stretches are returned in time order, adjacent and gapless, with
    one exception -- a stretch with nobody on the ice is not ice time and is
    left out (1 second across the golden twenty). The skater COUNT is not
    clamped here; that is :func:`line_combinations`' business, so a caller
    that wants to see the 1-skater gaps still can.

    This is also the lookup line metrics will want: which unit was on at time
    ``t`` is a bisect over one team's stretches.
    """
    team_of = _team_of_player(data.toi, data.roster)
    by_team: dict[int, dict[int, list[Span]]] = defaultdict(dict)
    for player_id, spans in skater_spans(data.toi, data.roster).items():
        team_id = team_of.get(player_id)
        if team_id is not None:
            by_team[team_id][player_id] = spans

    out: dict[int, list[Stretch]] = {}
    for team_id, players in by_team.items():
        on: dict[float, list[int]] = defaultdict(list)
        off: dict[float, list[int]] = defaultdict(list)
        for player_id, spans in players.items():
            for start, end in spans:
                on[start].append(player_id)
                off[end].append(player_id)

        cuts = sorted(set(on) | set(off))
        active: set[int] = set()
        stretches: list[Stretch] = []
        for index, start in enumerate(cuts[:-1]):
            # Off before on: the intervals are half-open, so a player whose
            # shift ends at this cut is already gone when the next one steps
            # on. (A player who leaves and returns at the same instant never
            # left -- merge_spans joined those two spans already.)
            active.difference_update(off[start])
            active.update(on[start])
            if active:
                stretches.append((start, cuts[index + 1], frozenset(active)))
        out[team_id] = stretches
    return out


def line_combinations(
    data,
    *,
    min_skaters: int = MIN_SKATERS,
    max_skaters: int = MAX_SKATERS,
    min_seconds: float = 0.0,
) -> dict[int, list[LineCombination]]:
    """team id -> every line combination that team used, longest TOI first.

    ``data`` is a ``Game`` or a ``GameData`` bundle. Each combination holds its
    skaters, its spans and therefore its TOI; see the module docstring for what
    the two bounds drop and why ``min_seconds`` exists.

    ``min_seconds`` is tested against the combination's TOTAL time, not
    against each span: a unit that played thirty seconds over three shifts is
    a unit, whereas one that totals a second and a half across two line
    changes is a change rather than a unit.
    """
    out: dict[int, list[LineCombination]] = {}
    for team_id, stretches in on_ice_stretches(data).items():
        spans_by_unit: dict[frozenset[int], list[Span]] = defaultdict(list)
        for start, end, players in stretches:
            if min_skaters <= len(players) <= max_skaters:
                spans_by_unit[players].append((start, end))

        units = []
        for players, spans in spans_by_unit.items():
            # Touching spans are joined: two stretches in a row can hold the
            # same five only if someone stepped on and off at that instant.
            # It does not happen in the games checked -- defensive, like the
            # merge in skater_spans.
            unit = LineCombination(team_id=team_id,
                                   players=tuple(sorted(players)),
                                   spans=tuple(merge_spans(spans)))
            if unit.toi >= min_seconds:
                units.append(unit)

        # Longest first, then by roster order, so the listing is stable
        # between runs and between sources.
        units.sort(key=lambda unit: (-unit.toi, unit.players))
        out[team_id] = units
    return out


# -- self-check ------------------------------------------------------------
# Stands in for the golden harness, which cannot sweep a module with no
# events in it. Prints one game's units and re-checks the two invariants the
# module docstring claims.

def check_toi_partition(data) -> dict[int, dict[str, float]]:
    """Per team: do the combinations account for exactly the ice time?

    Returns the two quantities the claim rests on -- how many skaters' totals
    disagree, and how many spans overlap inside one combination. Both are 0
    on every game checked.
    """
    report: dict[int, dict[str, float]] = {}
    units_by_team = line_combinations(data)
    for team_id, stretches in on_ice_stretches(data).items():
        own: dict[int, float] = defaultdict(float)
        for start, end, players in stretches:
            if MIN_SKATERS <= len(players) <= MAX_SKATERS:
                for player_id in players:
                    own[player_id] += end - start

        credited: dict[int, float] = defaultdict(float)
        overlaps = 0
        for unit in units_by_team.get(team_id, []):
            for player_id in unit.players:
                credited[player_id] += unit.toi
            overlaps += sum(1 for a, b in zip(unit.spans, unit.spans[1:])
                            if a[1] > b[0])

        report[team_id] = {
            "skaters": len(own),
            "toi_mismatches": sum(1 for player_id, seconds in own.items()
                                  if abs(seconds - credited[player_id]) > 1e-6),
            "span_overlaps": overlaps,
            "seconds": sum(unit.toi for unit in units_by_team.get(team_id, [])),
        }
    return report


if __name__ == "__main__":
    from pathlib import Path

    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    GAME_ID = 191504

    settings = Settings.from_env(project_root=Path(__file__).resolve().parents[2])
    game = build_game(RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir,
                              playsequence_source="playsequence_compiled"))

    def name(player_id: int) -> str:
        player = game.roster.players.get(player_id)
        if player is None:
            return str(player_id)
        return f"{player.last_name or player_id} ({player.position or '?'})"

    units_by_team = line_combinations(game)
    checks = check_toi_partition(game)
    for team in (game.info.home_team, game.info.away_team):
        units = units_by_team.get(team.id, [])
        named = sum(1 for unit in units if unit.toi >= 10)
        print(f"\n{team.name} ({team.id}): {len(units)} combinations, "
              f"{named} of 10s or more")
        for unit in units[:10]:
            print(f"  {unit.toi:7.1f}s  {unit.shifts:3d} shifts  "
                  f"{unit.size} skaters  "
                  f"{', '.join(name(p) for p in unit.players)}")
        check = checks[team.id]
        print(f"  {check['seconds']:.0f}s over {check['skaters']:.0f} skaters; "
              f"TOI mismatches {check['toi_mismatches']:.0f}, "
              f"span overlaps {check['span_overlaps']:.0f}")
