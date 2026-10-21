#!/usr/bin/python
"""Does a power play that an intermission cut in half still score?

THE QUESTION. A penalty taken in the last minute of a period is served in two
sittings: the rest of the period, then the start of the next one after a
fifteen-minute break, a fresh sheet of ice and a faceoff in centre instead of
wherever the puck was. The second sitting looks like a different kind of power
play from the first. Does it convert like one?

So: goals per 60 on the SECOND PART of an interrupted power play, against
goals per 60 on all power plays of the same season.

WHAT COUNTS AS A POWER PLAY HERE. A maximal contiguous run of
:class:`~hockey.metrics.on_ice_spans.SituationTimeline` stretches in which
this team held PP1 or PP2. That is manpower, not penalty bookkeeping, which
has two consequences worth knowing:

* two penalties back to back with no even-strength second between them are ONE
  episode here, and a 5v3 inside a 5v4 does not split it either;
* a penalty expiring at the intermission and a NEW one starting on the first
  faceoff of the next period are indistinguishable from one penalty carried
  over. Both read as one episode crossing the boundary. Penalty events would
  separate them; manpower cannot.

THE NUMERATOR COMES FROM THE SUPPLIER, NOT FROM THE TIMELINE. A power-play
goal ends the power play, so the goal sits exactly on the edge of the episode
and a half-open stretch test would drop it. Goals are therefore classified by
``manpower_of``, the supplier's own ``manpower_situation`` field, and only
LOCATED by the episode. The denominator is the timeline's seconds, which is
the same pairing ``on_ice.py`` uses for any per-60 rate.

REGULAR-SEASON OVERTIME IS EXCLUDED, numerator and denominator both: 3v3 is a
different game and a 4v3 in it is not the power play anybody means. Playoff
overtime is 5v5 hockey with real intermissions, so it stays -- which means a
power play carried from the third period into playoff overtime counts as
interrupted, because it was.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hockey.derive import context_filter as ctx
from hockey.metrics.on_ice_spans import SituationTimeline

#: The manpower values that mean "this team has the advantage".
POWERPLAY = (ctx.PP1, ctx.PP2)

GOAL = "goal"


@dataclass(frozen=True)
class Rate:
    """Goals, seconds, and the per-60 they make. Nothing clever."""
    label: str
    goals: int
    seconds: float
    episodes: int = 0

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    @property
    def per60(self) -> float:
        return 3600.0 * self.goals / self.seconds if self.seconds else 0.0

    def __str__(self) -> str:
        return (f"{self.label:38s} {self.goals:5d} goals  "
                f"{self.minutes:9.1f} min  {self.per60:6.2f} /60"
                + (f"  ({self.episodes} episodes)" if self.episodes else ""))


def pp_episodes(timeline: SituationTimeline, team_id: int, *,
                keep_ot: bool = True) -> list[tuple[float, float]]:
    """Maximal contiguous stretches in which ``team_id`` was on the power play.

    Contiguity is exact: a run continues only where one stretch ends at the
    next one's start. A dropped stretch -- the timeline discards a moment with
    only one team on the ice -- therefore breaks an episode rather than being
    bridged across, which is the conservative reading of a gap in the data.
    """
    runs: list[tuple[float, float]] = []
    current: tuple[float, float] | None = None
    for low, high, situations in timeline.slices:
        situation = situations.get(team_id)
        on_powerplay = (situation is not None and situation[1] in POWERPLAY
                        and (keep_ot or situation[0] != ctx.OT))
        if on_powerplay and current is not None and current[1] == low:
            current = (current[0], high)
        elif on_powerplay:
            if current is not None:
                runs.append(current)
            current = (low, high)
        elif current is not None:
            runs.append(current)
            current = None
    if current is not None:
        runs.append(current)
    return runs


def second_part(span: tuple[float, float]) -> tuple[float, float] | None:
    """The part of ``span`` after the intermission it crossed, or None.

    The cut is a period boundary strictly inside the span -- a power play
    ending exactly at the horn was not interrupted, it was over. The last such
    boundary wins, so the "second part" is always the final sitting.
    """
    low, high = span
    crossed = [boundary for boundary in
               range(ctx.PERIOD_LENGTH, int(high) + 1, ctx.PERIOD_LENGTH)
               if low < boundary < high]
    return (crossed[-1], high) if crossed else None


def _in_any(t: float, windows: Sequence[tuple[float, float]]) -> bool:
    """Both ends inclusive -- see the module docstring on the ending goal."""
    return any(low <= t <= high for low, high in windows)


def measure(bundles: Iterable, *, keep_ot: bool = True) -> tuple[Rate, Rate]:
    """``(second parts, all power plays)`` over any iterable of GameData.

    One pass per game: build the timeline, find each team's episodes, add up
    the seconds, then place each power-play goal in one bucket or both.
    """
    pp_goals = pp_seconds = 0.0
    cut_goals = cut_seconds = 0.0
    episodes = 0

    for data in bundles:
        timeline = SituationTimeline(data.toi, data.roster)
        if not timeline.slices:
            continue

        teams = sorted({team for _, _, situations in timeline.slices
                        for team in situations})
        windows: dict[int, list[tuple[float, float]]] = {}
        for team_id in teams:
            spans = pp_episodes(timeline, team_id, keep_ot=keep_ot)
            pp_seconds += sum(high - low for low, high in spans)
            tails = [tail for tail in (second_part(s) for s in spans) if tail]
            cut_seconds += sum(high - low for low, high in tails)
            episodes += len(tails)
            windows[team_id] = tails

        for event in data.events:
            if event.name != GOAL or event.team_id is None or event.t is None:
                continue
            if not keep_ot and ctx.period_of(event) == ctx.OT:
                continue
            if ctx.manpower_of(event) not in POWERPLAY:
                continue
            pp_goals += 1
            if _in_any(event.t, windows.get(event.team_id, ())):
                cut_goals += 1

    return (Rate("second part, after an intermission", int(cut_goals),
                 cut_seconds, episodes),
            Rate("every power play", int(pp_goals), pp_seconds))


def season(conn, league: int, season_name: str) -> tuple[Rate, Rate]:
    """The two rates for one league-season: regular season plus playoffs.

    Two passes rather than one, because the overtime rule depends on the
    stage: 3v3 regular-season overtime is dropped, playoff overtime is kept.
    The totals are added, so a goal is counted once under the rule that
    applies to the game it was scored in.
    """
    from hockey.db.game_query import PLAYOFFS, REGULAR, query_game_ids
    from hockey.metrics.game_bundles import from_database

    totals: list[list[Rate]] = []
    for stage, keep_ot in ((REGULAR, False), (PLAYOFFS, True)):
        games = query_game_ids(conn, league_sl_id=league, season=season_name,
                               stage=stage)
        if not games:
            continue
        print(f"   {stage:9s} {len(games):4d} games"
              + ("" if keep_ot else "  (overtime excluded)"))
        bundles = from_database(conn, games, names=[GOAL])
        totals.append(list(measure(bundles, keep_ot=keep_ot)))

    if not totals:
        raise SystemExit(f"no games for league {league}, season {season_name}")
    return tuple(  # type: ignore[return-value]
        Rate(parts[0].label, sum(p.goals for p in parts),
             sum(p.seconds for p in parts), sum(p.episodes for p in parts))
        for parts in zip(*totals))


def main() -> None:
    """Run it for the seasons the database actually holds.

    SHL 2025/26 is NOT one of them -- the `game` table has SHL 2026/27 only,
    55 games played so far. The complete 2025/26 season in there is league 17,
    Hockey Allsvenskan, 410 games including the playoffs. Both are printed
    rather than one being quietly substituted for the other.
    """
    from hockey.metrics.on_ice import open_connection

    conn = open_connection()
    try:
        # for league, season_name, name in ((17, "20252026", "Allsvenskan 2025/26"),
        #                                   (13, "20262027", "SHL 2026/27 so far")):
        #     print(f"\n{name}  (league {league}, season {season_name})")
        for league, season_name, name in ((13, "20252026", "SHL 2025/26"),
                                          (13, "20242025", "SHL 2024/25")):
            print(f"\n{name}  (league {league}, season {season_name})")

            cut, every = season(conn, league, season_name)
            print(f"\n   {cut}\n   {every}")
            if cut.seconds and every.per60:
                # The sample is small enough that the ratio needs this beside
                # it: 102 episodes of about a minute each is under two hours
                # of hockey. Expected = the goals those minutes would have
                # produced at the all-power-plays rate; one standard deviation
                # is its square root, Poisson.
                expected = every.per60 * cut.minutes / 60.0
                print(f"   ratio {cut.per60 / every.per60:.2f}x  "
                      f"-- {cut.goals} goals against {expected:.1f} expected "
                      f"at the overall rate, +/-{expected ** 0.5:.1f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
