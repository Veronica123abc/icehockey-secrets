#!/usr/bin/python
"""The metric catalog bound to one game: every lane, with its count.

``metric_catalog.py`` says what the lanes ARE; this says what they are worth
in a particular game. It is the game canvas's rail without the canvas -- the
same predicates, the same tree, the same numbers, printed instead of drawn::

    from hockey.derive.game_metrics import game_metrics

    metrics = game_metrics(game)
    metrics.print_tree()
    metrics.count("Shots · On Net")        # 61

NO METRIC IS DEFINED HERE, and not one predicate is respelled. Classification
is ``catalog.lanes_for_event`` -- the single call the canvas makes -- so a lane
counts here exactly what it counts on the rail, in the reports and in the
golden snapshot. What this module adds is one pass, a Counter, and a printer.

IT PRINTS THE WHOLE TREE, INCLUDING EMPTY LANES. The canvas drops a lane with
no events, which is right for a rail you have to scroll but wrong for reading
the catalog: a zero is a fact about the game (this league tags no cross-ice
dump-ins) and its absence is indistinguishable from a lane that does not exist.
Pass ``hide_empty=True`` for the canvas's view.

TEAMS ARE COLUMNS, not a filter. ``team_of`` decides whose event it is -- the
same answer the reports' for/against split uses -- so the two team columns sum
to the total except for events the supplier credits to nobody, which the
footer counts rather than hides.

A CONTEXT NARROWS BOTH THE COUNTS AND THE HEADER. ``context=None`` is every
situation, which is what makes the totals comparable to each module's own
``get_full_data``. Pass a ``ContextFilter`` and every lane is counted in that
situation instead, the way the canvas's context bar narrows its rail.

Run ``python -m hockey.derive.game_metrics`` to print one game.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from hockey.derive import context_filter as ctx
from hockey.derive import metric_catalog as catalog
from hockey.model.events import Event

# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings


@dataclass
class GameMetrics:
    """Every catalog lane, counted over one game.

    ``counts`` is lane key -> events matching it, and ``by_team`` the same
    split by the team the event is credited to. Both are plain dictionaries;
    nothing here is lazy, because one pass over a game's events is milliseconds
    and a half-populated object is harder to reason about than a full one.
    """
    game_id: int
    counts: dict[str, int]
    by_team: dict[int, dict[str, int]]
    team_ids: tuple[int, ...]
    team_labels: dict[int, str]
    total_events: int
    uncovered: dict[str, int]          # event name -> count, for names with no lane
    unattributed: int                  # events no team is credited with
    context: object | None = None

    # -- lookups ----------------------------------------------------------

    def count(self, lane_key: str, team_id: int | None = None) -> int:
        """One lane's count, for a team or for both.

        Raises on an unknown key rather than returning 0: a typo and a lane
        that genuinely never fired are different answers, and silently
        conflating them is how a report grows a column of zeros.
        """
        if lane_key not in catalog.BY_KEY:
            raise KeyError(f"unknown lane {lane_key!r}; run "
                           f"`python -m hockey.derive.metric_catalog` for the tree")
        if team_id is None:
            return self.counts.get(lane_key, 0)
        return self.by_team.get(team_id, {}).get(lane_key, 0)

    def events(self, lane_key: str, game) -> list[Event]:
        """The events behind one lane, recomputed from ``game``.

        Not stored: holding the lists for all 155 lanes would keep ~3 refs per
        event for the sake of a question usually asked about one lane.
        """
        lane = catalog.BY_KEY[lane_key]
        return [e for e in game.events
                if e.name == lane.event_name and lane.matches(e)
                and (self.context is None or self.context.matches(e))]

    def as_rows(self) -> list[tuple]:
        """``(section, population, group, item, key, total, *per team)``."""
        out = []
        for section in catalog.TREE:
            for population in section.populations:
                for lane in population.lanes:
                    out.append((section.label, population.label,
                                lane.group or "", lane.item, lane.key,
                                self.counts.get(lane.key, 0))
                               + tuple(self.count(lane.key, t)
                                       for t in self.team_ids))
        return out

    def to_dataframe(self):
        """The same rows as a DataFrame. pandas imported here so the module
        stays usable without it."""
        import pandas as pd
        columns = ["section", "population", "group", "item", "lane", "total"]
        columns += [self.team_labels.get(t, str(t)) for t in self.team_ids]
        return pd.DataFrame(self.as_rows(), columns=columns)

    # -- printing ---------------------------------------------------------

    def print_tree(self, hide_empty: bool = False, width: int = 46) -> None:
        """The whole catalog, indented, with this game's numbers beside it.

        The team columns are headed 'home' and 'away' rather than by name: a
        club name does not fit a number column, and truncating it is worse
        than naming both teams once in the title line above.
        """
        home, away = (self.team_labels.get(t, str(t)) for t in self.team_ids)
        situation = ("all situations" if self.context is None
                     else " · ".join(self.context.describe()))
        print(f"\ngame {self.game_id} — {home} (home) vs {away} (away)"
              f" · {self.total_events:,} events · {situation}")
        head = " " * width + "".join(f"{h:>8s}"
                                     for h in ("total", "home", "away"))
        print(f"\n{head}")
        print("-" * len(head))

        shown = 0
        for section in catalog.TREE:
            print(f"\n{section.label.upper()}")
            for population in section.populations:
                lanes = population.lanes
                if hide_empty and not any(self.counts.get(l.key) for l in lanes):
                    continue
                plural = "lane" if len(lanes) == 1 else "lanes"
                print(f"   {population.label}  "
                      f"(event '{population.event_name}', {len(lanes)} {plural})")
                grouped = [("", (population.all_lane,))] + list(population.groups)
                for group, group_lanes in grouped:
                    visible = [l for l in group_lanes
                               if not hide_empty or self.counts.get(l.key)]
                    if not visible:
                        continue
                    if group:
                        print(f"      {group}")
                    for lane in visible:
                        shown += 1
                        indent = 9 if group else 6
                        label = " " * indent + lane.item
                        cells = [self.counts.get(lane.key, 0)]
                        cells += [self.count(lane.key, t) for t in self.team_ids]
                        print(f"{label:<{width}s}"
                              + "".join(f"{c:>8,d}" for c in cells))

        covered = sum(self.counts.get(p.all_lane.key, 0)
                      for s in catalog.TREE for p in s.populations)
        print("-" * len(head))
        print(f"{shown} lanes shown of {len(catalog.LANES)} in the catalog")
        print(f"{covered:,} of {self.total_events:,} events belong to a population; "
              f"{sum(self.uncovered.values()):,} have no lane")
        if self.uncovered:
            top = ", ".join(f"{name} {n:,}" for name, n
                            in Counter(self.uncovered).most_common(8))
            print(f"   event names with no population: {top}")
        if self.unattributed:
            print(f"   {self.unattributed:,} counted events are credited to no "
                  f"team, so the team columns fall short of the total")


def game_metrics(game, context=None) -> GameMetrics:
    """Count every catalog lane over one game.

    ``game`` is a :class:`~hockey.model.game.Game` (from either loader).
    ``context`` is a ``ContextFilter``; None counts every situation.

    One pass over the events, classifying each with
    ``catalog.lanes_for_event`` -- the same call the canvas makes, so the
    numbers are the rail's.
    """
    counts: Counter[str] = Counter()
    by_team: dict[int, Counter[str]] = defaultdict(Counter)
    uncovered: Counter[str] = Counter()
    total = unattributed = 0

    for event in game.events:
        if not event.name or event.t is None:
            continue
        if context is not None and not context.matches(event):
            continue
        total += 1
        keys = catalog.lanes_for_event(event)
        if not keys:
            uncovered[event.name] += 1
            continue
        team = ctx.team_of(event)
        if team is None:
            unattributed += 1
        for key in keys:
            counts[key] += 1
            if team is not None:
                by_team[team][key] += 1

    info = game.info
    team_ids = (info.home_team.id, info.away_team.id)
    labels = {info.home_team.id: getattr(info.home_team, "name", None)
              or str(info.home_team.id),
              info.away_team.id: getattr(info.away_team, "name", None)
              or str(info.away_team.id)}
    return GameMetrics(
        game_id=game.game_id, counts=dict(counts),
        by_team={t: dict(c) for t, c in by_team.items()},
        team_ids=team_ids, team_labels=labels, total_events=total,
        uncovered=dict(uncovered), unattributed=unattributed, context=context)


if __name__ == "__main__":
    GAME_ID = 186451
    HIDE_EMPTY = False          # True for the canvas rail's view
    CONTEXT = None              # or ctx.DEFAULT for even strength

    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)
    metrics = game_metrics(build_game(raw), context=CONTEXT)
    metrics.print_tree(hide_empty=HIDE_EMPTY)
