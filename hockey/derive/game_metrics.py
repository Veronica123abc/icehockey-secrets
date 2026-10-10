#!/usr/bin/python
"""The metric catalog bound to some events: every lane, with its count.

``metric_catalog.py`` says what the lanes ARE; this says what they are worth
in a particular game. It is the game canvas's rail without the canvas -- the
same predicates, the same tree, the same numbers, printed instead of drawn::

    from hockey.derive.game_metrics import game_metrics

    metrics = game_metrics(game)           # a built Game
    metrics.print_tree()
    metrics.count("Shots · On Net")        # 61

EVENTS ARE THE PRIMITIVE, a game merely one way to get some. The counting
loop only ever reads ``event.name``, ``event.t`` and ``team_of(event)``, so
anything that yields Events works -- notably ``query_events``, whose results
may span a whole season, several players and both benches of every game::

    from hockey.db.event_query import query_events
    from hockey.derive.game_metrics import event_metrics

    events = query_events(conn, league_sl_id=17, season="20252026",
                          on_ice_player_sl_id=24417, with_on_ice=True)
    event_metrics(events).print_tree()

:func:`game_metrics` is a three-line wrapper over :func:`event_metrics` that
supplies the game's own events and labels its two teams home and away.

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
same answer the reports' for/against split uses -- so the team columns sum to
the total except for events the supplier credits to nobody, which the footer
counts rather than hides. A game has two; an arbitrary event list may have
twenty, so the columns are dropped past ``max_team_columns`` rather than
printing a table nobody can read. Pass ``teams=[...]`` to pick which ones.

WHAT THIS IS NOT. There is no for/against here, and no ice time. Both need to
know whose team a PLAYER was on, which is a question about rosters and shifts
rather than about events -- ``hockey/reports/on_ice.py`` answers it.

A CONTEXT NARROWS BOTH THE COUNTS AND THE HEADER. ``context=None`` is every
situation, which is what makes the totals comparable to each module's own
``get_full_data``. Pass a ``ContextFilter`` and every lane is counted in that
situation instead, the way the canvas's context bar narrows its rail.

Run ``python -m hockey.derive.game_metrics`` to print one game.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from hockey.derive import context_filter as ctx
from hockey.derive import metric_catalog as catalog
from hockey.model.events import Event

# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings


@dataclass
class LaneCounts:
    """Every catalog lane, counted over some events.

    ``counts`` is lane key -> events matching it, and ``by_team`` the same
    split by the team the event is credited to. Both are plain dictionaries;
    nothing here is lazy, because one pass over a game's events is milliseconds
    and a half-populated object is harder to reason about than a full one.
    """
    title: str                         # what the header calls this set
    games: tuple[int, ...]             # the game ids the events came from
    counts: dict[str, int]
    by_team: dict[int, dict[str, int]]
    team_ids: tuple[int, ...]          # column order
    team_labels: dict[int, str]        # heading per column
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

    def events(self, lane_key: str, source) -> list[Event]:
        """The events behind one lane, recomputed from ``source``.

        ``source`` is whatever was counted -- a Game or an iterable of Events;
        anything with ``.events`` is unwrapped. Not stored: holding the lists
        for all 159 lanes would keep ~3 refs per event for the sake of a
        question usually asked about one lane.
        """
        lane = catalog.BY_KEY[lane_key]
        return [e for e in getattr(source, "events", source)
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

    def print_tree(self, hide_empty: bool = False, width: int = 46,
                   max_team_columns: int = 6) -> None:
        """The whole catalog, indented, with these events' numbers beside it.

        Team columns are dropped when there are more than
        ``max_team_columns`` of them: a season's events for one player touch
        every opponent, and thirty numeric columns is not a table. The footer
        says so rather than leaving it a mystery.
        """
        teams = self.team_ids if len(self.team_ids) <= max_team_columns else ()
        situation = ("all situations" if self.context is None
                     else " · ".join(self.context.describe()))
        games = (f"{len(self.games)} games" if len(self.games) != 1
                 else f"game {self.games[0]}")
        print(f"\n{self.title} · {games} · {self.total_events:,} events"
              f" · {situation}")
        head = " " * width + "".join(
            f"{h:>8s}" for h in ("total",) + tuple(
                self.team_labels.get(t, str(t))[:8] for t in teams))
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
                        cells += [self.count(lane.key, t) for t in teams]
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
        if not teams and self.team_ids:
            print(f"   {len(self.team_ids)} teams in these events, more than "
                  f"max_team_columns -- per-team columns omitted; "
                  f"count(lane, team_id) still answers per team")


def event_metrics(events: Iterable[Event], *, context=None,
                  teams: Sequence[int] | None = None,
                  team_labels: dict[int, str] | None = None,
                  title: str = "events") -> LaneCounts:
    """Count every catalog lane over any iterable of Events.

    ``events`` is whatever produced them -- one game's, a season's, or a
    ``query_events`` result spanning several games, players and teams. One
    pass, classifying each with ``catalog.lanes_for_event``: the same call the
    canvas makes, so the numbers are the rail's.

    ``context`` is a ``ContextFilter``; None counts every situation.
    ``teams`` fixes the column order (default: every team seen, sorted) and
    ``team_labels`` their headings (default: the ids).
    """
    counts: Counter[str] = Counter()
    by_team: dict[int, Counter[str]] = defaultdict(Counter)
    uncovered: Counter[str] = Counter()
    games: set[int] = set()
    total = unattributed = 0

    for event in events:
        if not event.name or event.t is None:
            continue
        if context is not None and not context.matches(event):
            continue
        total += 1
        if event.game_id is not None:
            games.add(event.game_id)
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

    column_teams = (tuple(teams) if teams is not None
                    else tuple(sorted(by_team)))
    return LaneCounts(
        title=title, games=tuple(sorted(games)), counts=dict(counts),
        by_team={t: dict(c) for t, c in by_team.items()},
        team_ids=column_teams, team_labels=dict(team_labels or {}),
        total_events=total, uncovered=dict(uncovered),
        unattributed=unattributed, context=context)


def game_metrics(game, context=None) -> LaneCounts:
    """Count every catalog lane over one built ``Game``.

    A three-line wrapper over :func:`event_metrics`: it supplies the game's
    events, fixes the column order to home then away, and heads those columns
    'home' and 'away' -- a club name does not fit a number column, and the
    title line names both teams anyway.
    """
    info = game.info
    home, away = info.home_team, info.away_team
    return event_metrics(
        game.events, context=context, teams=(home.id, away.id),
        team_labels={home.id: "home", away.id: "away"},
        title=(f"{getattr(home, 'name', home.id)} (home) vs "
               f"{getattr(away, 'name', away.id)} (away)"))



if __name__ == "__main__":
    GAME_ID = 186451
    GAME_ID = 186802
    HIDE_EMPTY = False          # True for the canvas rail's view
    CONTEXT = None              # or ctx.DEFAULT for even strength


    # from hockey.db.event_query import query_events
    # from hockey.db.database import open_database_azure
    #
    # conn = open_database_azure()
    # events = query_events(conn, league_sl_id=17, season="20262027",
    #                       names=["shot", "goal", "controlledentry"],
    #                       with_on_ice=True)
    # m = event_metrics(events, title="league 17, 2026/27")
    #
    # print(m)
    # exit(0)


    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)
    metrics = game_metrics(build_game(raw), context=CONTEXT)
    metrics.print_tree(hide_empty=HIDE_EMPTY)
