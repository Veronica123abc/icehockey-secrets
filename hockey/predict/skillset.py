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
                                with a "weight" per raw unit of that value
    reference                   optional: the supplier's own scores for some
                                players, checked by ``python -m
                                hockey.predict.skillset <config>``

The weights are recovered by least squares from the supplier's portal, so they
belong to the league and season they were fitted on -- see each config's
``source``.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import hockey.derive.context_filter as ctx
from hockey.metrics.on_ice import Column, ColumnSet, open_connection, player_rows

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
        from hockey.metrics.cube import Cube
        from hockey.metrics.on_ice import cube_player_rows

        if not isinstance(cube, Cube):
            cube = Cube.load(cube)
        if self.stage is not None:
            cube = cube.slice(games=_games_in_stage(cube, self.stage))
        if players is None:
            players = [int(p) for p in cube.players.player_id]
        rows, missing = cube_player_rows(
            cube, players, columns=ColumnSet(tuple(self.columns.values())),
            context=self.context, min_toi=min_toi)
        return _score(self, rows), missing


@dataclass
class SkillsetRow:
    """One player: the sample, the inputs, and the score."""
    player_id: int
    name: str
    minutes: float                      # minutes in the skill set's context
    inputs: dict[str, float] = field(default_factory=dict)
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
        inputs.append(Input(name, spec.get("label", name), float(weight),
                            tuple(per20 or ()), tuple(ratio) if ratio else None))

    return Skillset(raw["name"], raw.get("label", raw["name"]), context,
                    raw.get("stage"), columns, float(raw["intercept"]),
                    tuple(inputs), raw)


def load_skillset(conn, players: Iterable, league: int, season: str,
                  config: str | Path | Skillset) -> tuple[list[SkillsetRow], list[str]]:
    """The skill set in ``config`` for ``players`` in one league season.

    Returns ``(rows, unanswered)`` like
    :func:`~hockey.metrics.on_ice.player_rows`, whose ``players`` rules apply:
    ids, names, or anything with a ``player_id``. ``config`` is a path, a
    config name ("skating"), or an already read :class:`Skillset`.
    """
    skillset = config if isinstance(config, Skillset) else read_skillset(config)
    rows, missing = player_rows(conn, players, league, season,
                                columns=ColumnSet(tuple(skillset.columns.values())),
                                context=skillset.context, stage=skillset.stage)
    return _score(skillset, rows), missing


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


def _score(skillset: Skillset, rows) -> list[SkillsetRow]:
    """The formula over :class:`~hockey.metrics.on_ice.PlayerRow`\ s."""
    out = []
    for row in rows:
        total = {name: row.totals.get(column.key, 0.0)
                 for name, column in skillset.columns.items()}
        values = {}
        for term in skillset.inputs:
            if term.ratio:
                num, den = (total[c] for c in term.ratio)
                values[term.name] = num / den if den else 0.0
            else:
                n = sum(total[c] for c in term.per20)
                values[term.name] = n / row.minutes * 20 if row.minutes else 0.0
        score = skillset.intercept + sum(t.weight * values[t.name] for t in skillset.inputs)
        out.append(SkillsetRow(row.player_id, row.name, row.minutes, values, score))
    return out


def _print_scores(skillset: Skillset, rows: list[SkillsetRow]) -> None:
    """A score table, best first, with each input's value."""
    names = [t.name for t in skillset.inputs]
    print(f"{'player':<26}{'min':>7}{'score':>9}" + "".join(f"  {n}" for n in names))
    for row in sorted(rows, key=lambda r: r.score, reverse=True):
        print(f"{row.name:<26}{row.minutes:7.1f}{row.score:9.3f}"
              + "".join(f"  {row.inputs[n]:>{len(n)}.3f}" for n in names))


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
