#!/usr/bin/python
"""Gamesets: which games a cube is built from, as a file rather than a call.

WHAT A GAMESET IS. One small JSON file naming a set of games and whose
skaters to credit, so building a cube is "build this gameset" instead of four
constants edited at the top of a script. It is the INPUT a cube was missing:
``meta.json`` inside a built cube records what happened, after the fact.

TWO KINDS, AND THE DIFFERENCE MATTERS. A gameset either states a QUERY or
lists the games OUTRIGHT:

* a query -- league, season, optionally a team and a stage -- is re-resolved
  every time it is built, so next week's games join it by themselves;
* ``game_ids`` is a literal list, which is the only way to express a cohort no
  query can describe: the games with a particular lineup, the games after a
  coaching change, the games somebody wrote on the back of an envelope. It is
  frozen by definition, and that is the point rather than a limitation.

Both are recorded in the file, so a number can always be traced to the set it
came from -- which a bare list of ids in a notebook cell cannot do.

WHY THEY LIVE IN THE REPOSITORY. ``hockey/config/gamesets/`` is version
controlled on purpose. A query-based gameset could be rebuilt from memory; a
hand-listed one could not, and that is exactly the sort of thing that gets
lost. Cubes themselves are the opposite -- large, derived, rebuildable -- so
they stay out, under ``CUBE_DIR``. Set ``GAMESET_DIR`` to keep gamesets
somewhere else.

THE FORMAT, with everything optional except a name and a way to find games::

    {
      "name": "DIF 2026/27, regular season",
      "note": "why this set exists -- read by a human, not by code",
      "league": 13,
      "season": "20262027",
      "team": 323,              # one team's games; omitted means the league's
      "stage": "regular",       # 'regular' (default), 'playoffs', null for all
      "limit": 10,              # the first N by date, after the query
      "game_ids": [215330],     # instead of the query: a literal cohort
      "players": "team",        # 'team', a list of ids, or null for everyone
      "cube": "dif_2627"        # the cube directory to write
    }

``players`` is the one worth understanding: it limits WHO is credited, not
what is counted. The for/against split still carries everything the opponent
did, so one team's skaters is the usual answer and is several times faster
than crediting all forty on the ice.
"""
from __future__ import annotations

import json
import os
import shutil
import warnings
from collections.abc import Iterable
from pathlib import Path

#: Where gamesets live. Inside the package, because they are small, hand
#: written and worth keeping; a cube is none of those things.
GAMESET_DIR = Path(os.environ.get(
    "GAMESET_DIR",
    Path(__file__).resolve().parents[1] / "config" / "gamesets"))

#: Where built cubes go. The same default ``cube_api`` serves from.
CUBE_DIR = Path(os.environ.get("CUBE_DIR", "output/cubes"))

#: Every key a gameset may carry. Anything else is a typo, and a typo in a
#: config file is silent unless something refuses it -- "teams" instead of
#: "team" would quietly build the whole league.
_KEYS = {"name", "note", "league", "season", "team", "stage", "limit",
         "game_ids", "players", "cube"}

_DEFAULT_STAGE = "regular"


class GamesetError(ValueError):
    """A gameset that cannot be read, or asks for something impossible."""


def _path(name: str) -> Path:
    """The file for a gameset name, refusing anything outside the directory."""
    candidate = (GAMESET_DIR / f"{name}.json" if not name.endswith(".json")
                 else GAMESET_DIR / name)
    resolved = candidate.resolve()
    if GAMESET_DIR.resolve() not in resolved.parents:
        raise GamesetError(f"{name!r} is outside {GAMESET_DIR}")
    return resolved


def available() -> list[dict]:
    """Every gameset on disk, as ``{name, cube, built, summary}``."""
    out: list[dict] = []
    if not GAMESET_DIR.is_dir():
        return out
    for path in sorted(GAMESET_DIR.glob("*.json")):
        try:
            config = load(path.stem)
        except GamesetError as problem:
            out.append({"name": path.stem, "error": str(problem)})
            continue
        cube = CUBE_DIR / config["cube"]
        out.append({"name": path.stem, "cube": config["cube"],
                    "built": (cube / "meta.json").is_file(),
                    "summary": describe(config)})
    return out


def load(name: str) -> dict:
    """One gameset, validated. Raises :class:`GamesetError` on anything odd."""
    path = _path(name)
    if not path.is_file():
        raise GamesetError(f"no gameset {name!r} in {GAMESET_DIR}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as problem:
        raise GamesetError(f"{path.name}: {problem}") from problem
    if not isinstance(config, dict):
        raise GamesetError(f"{path.name}: expected an object")

    unknown = sorted(set(config) - _KEYS)
    if unknown:
        raise GamesetError(
            f"{path.name}: unknown key(s) {unknown}; known keys are "
            f"{sorted(_KEYS)}")
    if not config.get("game_ids") and not (config.get("league")
                                           and config.get("season")):
        raise GamesetError(
            f"{path.name}: needs either 'game_ids', or 'league' and 'season' "
            f"to query by")
    players = config.get("players")
    if players not in (None, "team") and not isinstance(players, list):
        raise GamesetError(
            f"{path.name}: 'players' is 'team', a list of ids, or null; "
            f"got {players!r}")
    if players == "team" and not config.get("team"):
        raise GamesetError(f"{path.name}: 'players': 'team' needs a 'team'")
    config.setdefault("cube", path.stem)
    config.setdefault("name", path.stem)
    return config


def describe(config: dict) -> str:
    """The gameset in one line, for a listing."""
    if config.get("game_ids"):
        where = f"{len(config['game_ids'])} games listed by hand"
    else:
        where = f"league {config['league']}, season {config['season']}"
        if config.get("team"):
            where += f", team {config['team']}"
        stage = config.get("stage", _DEFAULT_STAGE)
        where += f", {stage or 'every stage'}"
        if config.get("limit"):
            where += f", first {config['limit']}"
    players = config.get("players")
    whose = ("one team's skaters" if players == "team"
             else f"{len(players)} players" if isinstance(players, list)
             else "every skater on the ice")
    return f"{where}; crediting {whose}"


def resolve(conn, config: dict) -> tuple[list[int], list[int] | None]:
    """``(game ids, player ids or None)`` for a loaded gameset.

    A literal ``game_ids`` is taken as given; otherwise the schedule is
    queried, in the order games were played, so ``limit`` means the FIRST N of
    the season rather than an arbitrary N.
    """
    from hockey.db.game_query import query_game_ids

    if config.get("game_ids"):
        games = [int(g) for g in config["game_ids"]]
    else:
        games = query_game_ids(conn, league_sl_id=int(config["league"]),
                               season=str(config["season"]),
                               stage=config.get("stage", _DEFAULT_STAGE),
                               team_sl_ids=config.get("team"))
        if config.get("limit"):
            games = games[:int(config["limit"])]
    if not games:
        raise GamesetError(f"{config['name']}: the selection names no games")

    players = config.get("players")
    if players == "team":
        from hockey.helpers.get_roster import get_roster
        players = [p.player_id for p in get_roster(int(config["team"]),
                                                   str(config["season"]), conn)]
    elif isinstance(players, list):
        players = [int(p) for p in players]
    else:
        players = None
    return games, players


def build(conn, name: str, *, cube_dir: Path | str | None = None,
          progress: bool = True) -> Path:
    """Resolve a gameset, build its cube, save it, return the directory."""
    from hockey.metrics.cube import build_cube

    config = load(name)
    games, players = resolve(conn, config)
    if progress:
        print(f"{config['name']}: {describe(config)}")
        print(f"   {len(games)} games"
              + (f", {len(players)} players" if players else ""))
    cube = build_cube(conn, games, players=players, progress=progress)
    directory = Path(cube_dir or CUBE_DIR) / config["cube"]
    _save(cube, directory, progress)
    return directory


def update(conn, name: str, *, cube_dir: Path | str | None = None,
           progress: bool = True) -> Path:
    """Bring a gameset's cube up to date: count only the games it lacks.

    What to run after a round. The gameset is resolved again, so a query
    picks up the games played since, and :meth:`~hockey.metrics.cube.Cube.extend`
    counts just those -- the rest of the season is not touched. A cube that
    does not exist yet, or was saved one row per lane, is built from scratch.

    A game already in the cube is never counted again, so one that was
    ingested half-finished stays half-finished: delete the cube to rebuild it.
    """
    from hockey.metrics.cube import Cube

    config = load(name)
    directory = Path(cube_dir or CUBE_DIR) / config["cube"]
    if not (directory / "meta.json").is_file():
        return build(conn, name, cube_dir=cube_dir, progress=progress)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cube = Cube.load(directory)
    if cube.per_lane:
        if progress:
            print(f"{config['name']}: saved one row per lane -- rebuilding")
        return build(conn, name, cube_dir=cube_dir, progress=progress)
    for warning in caught:
        warnings.warn(warning.message, warning.category, stacklevel=2)

    games, players = resolve(conn, config)
    new = sorted(set(games) - set(cube.games))
    if progress:
        print(f"{config['name']}: {len(cube.games)} games in the cube, "
              f"{len(new)} new")
    if not new:
        return directory
    _save(cube.extend(conn, new, players=players, progress=progress),
          directory, progress)
    return directory


def _save(cube, directory: Path, progress: bool) -> None:
    """Save beside the old cube, then swap: a crash halfway through a save
    leaves the previous cube whole rather than a mixture of the two."""
    staging = directory.with_name(directory.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    cube.save(staging)
    if directory.exists():
        shutil.rmtree(directory)
    staging.rename(directory)
    if progress:
        size = sum(f.stat().st_size for f in directory.glob("*")) / 1e6
        print(f"   {cube}\n   saved to {directory}  ({size:.1f} MB)")


def main() -> None:
    """List every gameset, then build the cubes that are missing and bring
    the others up to date with any games played since.

    No arguments: adding a gameset is adding a file, and rebuilding one is
    deleting its cube directory. Both are things you can do without flags.
    Run it after every round; a cube with nothing new costs one schedule
    query.
    """
    from hockey.metrics.on_ice import open_connection

    sets = available()
    print(f"\ngamesets in {GAMESET_DIR}")
    print(f"cubes in    {CUBE_DIR.resolve()}\n")
    if not sets:
        print("None. Add a JSON file -- see this module's docstring for the "
              "format.")
        return
    for entry in sets:
        if "error" in entry:
            print(f"  !  {entry['name']:24s} {entry['error']}")
            continue
        mark = "ok" if entry["built"] else "--"
        print(f"  {mark} {entry['name']:24s} -> {entry['cube']:20s} "
              f"{entry['summary']}")

    valid = [e for e in sets if "error" not in e]
    if not valid:
        return
    print(f"\nupdating {len(valid)} cube(s); delete a cube directory to "
          f"rebuild it from scratch")
    conn = open_connection()
    try:
        for entry in valid:
            print()
            update(conn, entry["name"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
