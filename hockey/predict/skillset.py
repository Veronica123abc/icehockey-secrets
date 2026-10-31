#!/usr/bin/python
"""Skill sets in the supplier's sense, computed from our lanes.

WHAT A SKILL SET IS. The supplier's Player Analysis scores a player on
"skills" -- Skating, Shooting, ... -- per archetype (Offensive Forwards, ...).
Each skill is a fixed linear combination of a handful of per-player event
metrics::

    score = intercept + sum(weight[input] * value[input])

One JSON file in ``hockey/predict/skillsets/`` describes one skill set, and
:func:`load_skillset` computes it for any players. Nothing here knows about
Skating; ``skillsets/skating.json`` is the first config and the template.

THE CONFIG, top to bottom:

    name, label, description    what it is
    source, notes               where the weights come from and what they
                                hold for -- free text, not read by the code
    context                     the situation, as ``context_filter`` dimension
                                -> values (e.g. "Period": ["P1", "P2", "P3"]),
                                applied on top of ``context_filter.DEFAULT``
    stage                       "regular", or null for the whole season
    side                        whose events count, unless a count says otherwise:
                                "credited"  the player's own (event.player_id)
                                "for"       his team's, while he is on the ice
                                "against"   the opponents', while he is on the ice
                                "both"      either team's, while he is on the ice
    counts                      name -> catalog lanes, ANDed across groups like a
                                :class:`~hockey.metrics.on_ice.Column`. Either
                                a list of lanes, counted on the top-level side,
                                or {"lanes": [...], "side": "for"} for its own
    intercept, inputs           the formula. An input is EITHER
                                  "per20": [count, ...]  sum of counts per 20
                                                         minutes of the context
                                  "ratio": [num, den]    a share, 0 when den is 0
                                with a "weight" per raw unit of that value, or
                                per league standard deviation when the input
                                also carries "mean" and "std": then the weight
                                multiplies (value - mean) / std
    normalization               written by :func:`normalize`: the cube and
                                cutoff the means and deviations came from
    team_normalization          the same for "team_mean" and "team_std", the
                                team stats written by ``normalize(teams=True)``
    reference                   optional: the supplier's own scores for some
                                players, checked by ``python -m
                                hockey.predict.skillset <config>``

The weights are recovered by least squares from the supplier's portal, so they
belong to the league and season they were fitted on -- see each config's
``source``.

NORMALISING. :func:`normalize` fills in each input's "mean" and "std" from
every player a cube credits, so a league cube rescored after each round puts
every input in league standard deviations. A ratio is normalised as the ratio,
not count by count. A value that does not exist -- a ratio whose denominator
is 0, a rate over no minutes -- counts as the league mean once normalised,
and is left out of the mean and deviation themselves. Supplier-fitted
configs are not normalised: their weights are per raw unit.

TEAMS. :meth:`Skillset.team_rows` and :func:`load_team_skillset` score teams
with the same config. Two things differ, both because a team is not a big
player:

* "credited" is counted as "for". What a team's players did is what the team
  did, so the team's own events are the natural reading -- and one event is
  counted once, not once per skater on the ice.
* "per20" is per 20 minutes of GAME time in the context, not ice time, so a
  team's rates are several times a player's. Player means and deviations
  would put every team far above the league; a team is normalised by
  "team_mean" and "team_std", against other teams.
"""
from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import hockey.derive.context_filter as ctx
from hockey.metrics.on_ice import (CREDITED, FOR, Column, ColumnSet, open_connection,
                                   player_rows)

#: Where the configs live; :func:`read_skillset` also accepts a bare name.
SKILLSET_DIR = Path(__file__).parent / "skillsets"


@dataclass(frozen=True)
class Input:
    """One term of the formula: a per-20 sum of counts, or a ratio of two."""
    name: str
    label: str
    weight: float
    per20: tuple[str, ...] = ()
    ratio: tuple[str, str] | None = None
    mean: float | None = None           # both set: the weight is per std
    std: float | None = None
    team_mean: float | None = None      # the same, against other teams
    team_std: float | None = None


@dataclass(frozen=True)
class Skillset:
    """A config file, read and checked."""
    name: str
    label: str
    context: ctx.ContextFilter
    stage: str | None
    columns: dict[str, Column]          # count name -> column
    intercept: float
    inputs: tuple[Input, ...]
    raw: dict                           # the whole file, for source/notes/reference

    def player_rows(self, cube, players: Iterable | None = None, *,
                    min_toi: float = 0.0) -> tuple[list[SkillsetRow], list[str]]:
        """This skill set for the players of a built cube, without a database.

        ``cube`` is a :class:`~hockey.metrics.cube.Cube` or the directory it
        was saved to; ``players`` defaults to everyone it credits, which is
        what a league cube scored for normalisation wants. The games are the
        cube's, narrowed to this skill set's ``stage`` -- slice the cube first
        for a cohort. ``min_toi`` drops players with that many minutes or fewer
        in the skill set's context; they come back in the unanswered list.
        """
        rows, missing = self._cube_rows(cube, players, min_toi)
        return _score(self, rows), missing

    def team_rows(self, cube, teams: Iterable[int] | None = None, *,
                  min_toi: float = 0.0) -> list[SkillsetRow]:
        """This skill set for the teams of a built cube. A row's ``player_id``
        is the team id and ``minutes`` is game time in the context."""
        return _score(self, self._cube_team_rows(cube, teams, min_toi), teams=True)

    @property
    def team_columns(self) -> dict[str, Column]:
        """:attr:`columns` as a team counts them: credited becomes for."""
        return {name: Column(c.heading, c.lanes, FOR if c.side == CREDITED else c.side,
                             c.weight, rate=False)
                for name, c in self.columns.items()}

    def _stage_cube(self, cube):
        from hockey.metrics.cube import Cube

        if not isinstance(cube, Cube):
            cube = Cube.load(cube)
        if self.stage is not None:
            cube = cube.slice(games=_games_in_stage(cube, self.stage))
        return cube

    def _cube_rows(self, cube, players, min_toi):
        """The unscored PlayerRows behind :meth:`player_rows`."""
        from hockey.metrics.on_ice import cube_player_rows

        cube = self._stage_cube(cube)
        if players is None:
            players = [int(p) for p in cube.players.player_id]
        return cube_player_rows(
            cube, players, columns=ColumnSet(tuple(self.columns.values())),
            context=self.context, min_toi=min_toi)

    def _cube_team_rows(self, cube, teams, min_toi):
        """The unscored TeamRows behind :meth:`team_rows`."""
        from hockey.metrics.on_ice import cube_team_rows

        return cube_team_rows(
            self._stage_cube(cube), teams,
            columns=ColumnSet(tuple(self.team_columns.values())),
            context=self.context, min_toi=min_toi)


@dataclass
class SkillsetRow:
    """One player: the sample, the inputs, and the score."""
    player_id: int
    name: str
    minutes: float                      # minutes in the skill set's context
    inputs: dict[str, float] = field(default_factory=dict)       # raw values
    normalized: dict[str, float] = field(default_factory=dict)   # what is weighted
    score: float = 0.0


def read_skillset(config: str | Path) -> Skillset:
    """Read a config: a path, or the name of one in :data:`SKILLSET_DIR`.

    Raises ValueError when an input names a count that is not defined, has
    neither or both of per20/ratio, or carries a weight that is not a number.
    Unknown lanes fail in :class:`~hockey.metrics.on_ice.Column` itself.
    """
    path = Path(config)
    if not path.suffix and not path.exists():
        path = SKILLSET_DIR / f"{config}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    where = f"{path.name}"

    context = ctx.DEFAULT
    for dimension, values in raw.get("context", {}).items():
        context = context.with_values(dimension, values)

    default_side = raw.get("side", "credited")
    columns = {}
    for name, spec in raw["counts"].items():
        lanes, side = ((spec, default_side) if isinstance(spec, list)
                       else (spec["lanes"], spec.get("side", default_side)))
        columns[name] = Column(name, tuple(lanes), side, rate=False)

    inputs = []
    for spec in raw["inputs"]:
        name = spec["name"]
        per20, ratio = spec.get("per20"), spec.get("ratio")
        if (per20 is None) == (ratio is None):
            raise ValueError(f"{where}: input {name!r} needs exactly one of per20 / ratio")
        if ratio is not None and len(ratio) != 2:
            raise ValueError(f"{where}: input {name!r}: ratio is [numerator, denominator]")
        for count in per20 or ratio:
            if count not in columns:
                raise ValueError(f"{where}: input {name!r} uses undefined count {count!r}")
        weight = spec["weight"]
        if not isinstance(weight, (int, float)) or not math.isfinite(weight):
            raise ValueError(f"{where}: input {name!r} has weight {weight!r}")
        stats = [_stats(spec, f"{where}: input {name!r}", prefix)
                 for prefix in ("", "team_")]
        inputs.append(Input(name, spec.get("label", name), float(weight),
                            tuple(per20 or ()), tuple(ratio) if ratio else None,
                            *stats[0], *stats[1]))

    return Skillset(raw["name"], raw.get("label", raw["name"]), context,
                    raw.get("stage"), columns, float(raw["intercept"]),
                    tuple(inputs), raw)


def _stats(spec: dict, where: str, prefix: str) -> tuple[float | None, float | None]:
    """An input's ``<prefix>mean`` and ``<prefix>std``: both or neither."""
    mean, std = spec.get(f"{prefix}mean"), spec.get(f"{prefix}std")
    if (mean is None) != (std is None):
        raise ValueError(f"{where} needs both {prefix}mean and {prefix}std, or neither")
    if mean is None:
        return None, None
    if not (isinstance(mean, (int, float)) and math.isfinite(mean)
            and isinstance(std, (int, float)) and math.isfinite(std) and std > 0):
        raise ValueError(f"{where} has {prefix}mean {mean!r}, {prefix}std {std!r}")
    return float(mean), float(std)


def load_skillset(conn, players: Iterable, league: int, season: str,
                  config: str | Path | Skillset, *,
                  min_toi: float = 0.0) -> tuple[list[SkillsetRow], list[str]]:
    """The skill set in ``config`` for ``players`` in one league season.

    Returns ``(rows, unanswered)`` like
    :func:`~hockey.metrics.on_ice.player_rows`, whose ``players`` rules apply:
    ids, names, or anything with a ``player_id``. ``config`` is a path, a
    config name ("skating"), or an already read :class:`Skillset`.
    ``min_toi`` drops players with that many minutes or fewer in the skill
    set's context; they come back in the unanswered list.
    """
    skillset = config if isinstance(config, Skillset) else read_skillset(config)
    rows, missing = player_rows(conn, players, league, season,
                                columns=ColumnSet(tuple(skillset.columns.values())),
                                context=skillset.context, stage=skillset.stage,
                                min_toi=min_toi)
    return _score(skillset, rows), missing


def load_team_skillset(conn, teams: Iterable[int] | None, league: int, season: str,
                       config: str | Path | Skillset, *,
                       min_toi: float = 0.0) -> list[SkillsetRow]:
    """The skill set in ``config`` for teams in one league season, from the
    database; ``teams`` None is every team. See :meth:`Skillset.team_rows`."""
    from hockey.metrics.on_ice import team_rows

    skillset = config if isinstance(config, Skillset) else read_skillset(config)
    rows = team_rows(conn, teams, league, season,
                     columns=ColumnSet(tuple(skillset.team_columns.values())),
                     context=skillset.context, stage=skillset.stage, min_toi=min_toi)
    return _score(skillset, rows, teams=True)


def _games_in_stage(cube, stage: str) -> list[int]:
    """The cube's games in one stage. The regular season also admits a game
    with no stage recorded, as :func:`~hockey.db.game_query.query_game_ids`
    does."""
    from hockey.db.game_query import REGULAR

    info = cube.game_info
    if not len(info):
        raise ValueError(f"this cube records no stages; rebuild it, or set the "
                         f"skill set's stage to null")
    stages = info.stage.fillna("").astype(str)
    keep = (stages == stage) | ((stages == "") if stage == REGULAR else False)
    return [int(g) for g in info.game_id[keep]]


def _values(skillset: Skillset, row, *, teams: bool = False) -> dict[str, float | None]:
    """Each input's raw value for one PlayerRow or TeamRow; None where it does
    not exist (a ratio over 0, a rate over no minutes)."""
    columns = skillset.team_columns if teams else skillset.columns
    total = {name: row.totals.get(column.key, 0.0) for name, column in columns.items()}
    values = {}
    for term in skillset.inputs:
        if term.ratio:
            num, den = (total[c] for c in term.ratio)
            values[term.name] = num / den if den else None
        else:
            n = sum(total[c] for c in term.per20)
            values[term.name] = n / row.minutes * 20 if row.minutes else None
    return values


def _score(skillset: Skillset, rows, *, teams: bool = False) -> list[SkillsetRow]:
    """The formula over :class:`~hockey.metrics.on_ice.PlayerRow`\ s, or
    TeamRows with ``teams``, which normalises by the team stats."""
    out = []
    for row in rows:
        values = _values(skillset, row, teams=teams)
        normalized = {}
        for term in skillset.inputs:
            value = values[term.name]
            mean, std = (term.team_mean, term.team_std) if teams else (term.mean, term.std)
            if mean is None:
                normalized[term.name] = 0.0 if value is None else value
            else:  # a missing value is the league mean
                normalized[term.name] = 0.0 if value is None else (value - mean) / std
        score = skillset.intercept + sum(t.weight * normalized[t.name] for t in skillset.inputs)
        raw = {name: 0.0 if value is None else value for name, value in values.items()}
        out.append(SkillsetRow(row.player_id, row.name, row.minutes, raw, normalized, score))
    return out


def normalize(config: str | Path, cube, *, min_toi: float = 0.0,
              teams: bool = False) -> Skillset:
    """Recompute every input's "mean" and "std" from a cube and write them
    into the config file. Returns the skill set as now saved.

    ``teams`` computes "team_mean" and "team_std" instead, from every team in
    the cube -- a league cube's whole league; a team cube's one team and the
    opponents it met, which is rarely what is wanted. ``min_toi`` is then game
    minutes.

    ``cube`` is a :class:`~hockey.metrics.cube.Cube` or its directory -- a
    league cube for league units, a team cube to rank within a team. Every
    player it credits counts once, in the skill set's own context and stage,
    unless he has ``min_toi`` minutes or fewer: a few minutes of ice time
    give a rate far from anyone's true one, and they widen the deviation for
    everybody. The deviation is the population one, so the cube's own players
    come out with exactly mean 0 and std 1.
    """
    from hockey.metrics.cube import Cube

    path = Path(config)
    if not path.suffix and not path.exists():
        path = SKILLSET_DIR / f"{config}.json"
    skillset = read_skillset(path)
    if "reference" in skillset.raw:
        raise ValueError(f"{path.name} holds supplier-fitted weights, per raw unit; "
                         f"normalising would change what they mean")
    source = None
    if not isinstance(cube, Cube):
        source = Path(cube).name
        cube = Cube.load(cube)

    if teams:
        rows = skillset._cube_team_rows(cube, None, min_toi)
    else:
        rows, _ = skillset._cube_rows(cube, None, min_toi)
    values = [_values(skillset, row, teams=teams) for row in rows]
    prefix = "team_" if teams else ""
    for spec in skillset.raw["inputs"]:
        sample = [v[spec["name"]] for v in values if v[spec["name"]] is not None]
        if len(sample) < 2 or statistics.pstdev(sample) == 0:
            raise ValueError(f"input {spec['name']!r} takes fewer than two values "
                             f"in this cube; cannot normalise it")
        spec[f"{prefix}mean"] = statistics.fmean(sample)
        spec[f"{prefix}std"] = statistics.pstdev(sample)
    skillset.raw[f"{prefix}normalization"] = {
        "cube": source, "games": len(cube.games),
        "teams" if teams else "players": len(rows), "min_toi": min_toi,
        "computed": date.today().isoformat()}
    path.write_text(json.dumps(skillset.raw, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return read_skillset(path)


def _print_scores(skillset: Skillset, rows: list[SkillsetRow]) -> None:
    """A score table, best first, with the value each weight multiplies:
    normalised where the input carries a mean and std, raw otherwise."""
    names = [t.name for t in skillset.inputs]
    print(f"{'name':<26}{'min':>7}{'score':>9}" + "".join(f"  {n}" for n in names))
    for row in sorted(rows, key=lambda r: r.score, reverse=True):
        print(f"{row.name:<26}{row.minutes:7.1f}{row.score:9.3f}"
              + "".join(f"  {row.normalized[n]:>{len(n)}.3f}" for n in names))


def _check_reference(skillset: Skillset, reference: dict, conn) -> None:
    """Our scores against the supplier's for the players in ``reference``."""
    expected = {int(k): v for k, v in reference["scores"].items()}
    rows, missing = load_skillset(conn, list(expected), reference["league"],
                                  reference["season"], skillset)
    print(f"{skillset.label}: {len(rows)} players")
    print(f"{'player':<26}{'min':>7}{'ours':>8}{'portal':>8}{'diff':>8}")
    for row in rows:
        print(f"{row.name:<26}{row.minutes:7.1f}{row.score:8.3f}"
              f"{expected[row.player_id]:8.3f}{row.score - expected[row.player_id]:+8.3f}")
    if rows:
        mean = sum(abs(r.score - expected[r.player_id]) for r in rows) / len(rows)
        print(f"mean |diff| {mean:.4f}")
    if missing:
        print("unanswered:", missing)


if __name__ == "__main__":
    # With a "reference" and no --team: check the config against the
    # supplier's own scores. Otherwise: score one team's roster.
    import argparse

    from hockey.helpers.get_roster import get_roster

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", nargs="?", default="my_skillset", #skating",
                        help="a config name in skillsets/ or a path (default: skating)")
    parser.add_argument("--team", type=int,
                        help="SportLogIQ team id whose roster to score (default: 323)")
    parser.add_argument("--league", type=int, default=13)
    parser.add_argument("--season", default="20262027")
    args = parser.parse_args()

    skillset = read_skillset(args.config)
    reference = skillset.raw.get("reference")
    conn = open_connection()
    try:
        if reference and args.team is None:
            _check_reference(skillset, reference, conn)
        else:
            team = 323 if args.team is None else args.team
            players = [p.player_id for p in get_roster(team, args.season, conn)]
            rows, missing = load_skillset(conn, players, args.league, args.season, skillset)
            print(f"{skillset.label}: team {team}, league {args.league}, "
                  f"season {args.season}, {len(rows)} players")
            _print_scores(skillset, rows)
            if missing:
                print("unanswered:", missing)
    finally:
        conn.close()
