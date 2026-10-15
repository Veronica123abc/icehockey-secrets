"""The cube explorer: picking metrics by clicking, for someone who won't write Python.

WHAT THIS SERVES. One page, ``/explore``, and the endpoints behind it. The
page is three panes -- the metric tree, what to narrow it to, and a table --
and every click is a filter on a cube (``hockey/metrics/cube.py``) that was
built in advance. Nothing here aggregates: it slices a DataFrame and formats
the result, which is why a click answers in milliseconds rather than in the
seconds a fresh database read would take.

WRITTEN FOR SOMEONE WHO DOES NOT KNOW THE VOCABULARY. Three deliberate
choices follow from that:

* THE TREE CARRIES ITS DESCRIPTIONS. Every lane is shipped with whatever
  ``hockey/derive/lane_docs.py`` has for it, and lanes with nothing written
  are MARKED as undescribed rather than quietly looking the same as the rest.
  The gaps are visible to the person filling them in, in the place they matter.
* "CONTEXT" IS NOT A WORD ON THE PAGE. The situation is offered as presets --
  even strength, power play, shorthanded, everything -- with the five manpower
  values and three goalie situations behind an "advanced" disclosure. The
  presets are built from ``context_filter``'s own constants, so they cannot
  drift from what the reports mean by the same words.
* THE SAMPLE IS NEVER OPTIONAL. Games played and minutes are columns of every
  table, because a coach who slices one game down to the power play is looking
  at two minutes of hockey and a per-60 rate of 180. The number is right; the
  reading is not, and only the sample beside it says so.

PLAYER AND TEAM ARE TWO TABLES, NOT A TOGGLE OVER ONE. Summing a lane over a
team's players counts each event once per skater on the ice -- about five
times over. The cube keeps a separate team-attributed table for exactly that
reason, and this API picks one or the other rather than adding up the wrong
one. See the cube module docstring.

NO DATABASE. A cube is files, so this whole page works in any ``GAME_SOURCE``
mode and on a worker with no credentials. Game labels come from the bundled
team manifest for the same reason.
"""
from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

# The one implementation of the path-traversal guard, rather than a second
# copy of the same check: a cube name arrives from the URL.
from filter_api import _is_safe_segment

cube_bp = Blueprint("cube", __name__)
_log = logging.getLogger(__name__)

#: Where built cubes live. Cubes are data, not code, so this is a path like
#: DATA_ROOT_DIR rather than something inside the package -- a deployment
#: replaces the package and would take the cubes with it.
CUBE_DIR = Path(os.environ.get("CUBE_DIR", "output/cubes"))

#: Cubes retained per worker. A team-season is ~1MB on disk and a few times
#: that in memory, so this is small for the same reason GAME_CACHE_SIZE is.
CUBE_CACHE_SIZE = int(os.environ.get("CUBE_CACHE_SIZE", "2"))
_cube_cache: "OrderedDict[str, object]" = OrderedDict()

#: Plain words for the situation values. The keys are ``context_filter``'s own
#: constants, so a renamed value breaks this loudly rather than silently
#: mislabelling a filter.
_MANPOWER_LABELS = {
    "ES": "Even strength", "PP1": "Power play, one man up",
    "PP2": "Power play, two men up", "SH1": "Shorthanded, one man down",
    "SH2": "Shorthanded, two men down",
}
_PERIOD_LABELS = {"P1": "1st period", "P2": "2nd period", "P3": "3rd period",
                  "OT": "Overtime"}


def _presets() -> list[dict]:
    """The situation choices offered first, built from the real constants.

    ``EVEN_STRENGTH`` is the reports' definition and not ``ctx.DEFAULT``: even
    manpower whatever the goalies are doing, because a pulled goalie buys an
    extra attacker rather than an advantage. Taking it from ``on_ice`` rather
    than restating it is what keeps the page and the PDFs agreeing.
    """
    from hockey.derive import context_filter as ctx
    from hockey.metrics.on_ice import EVEN_STRENGTH

    goalies = list(ctx.GOALIE_SITUATIONS)
    return [
        {"id": "even", "label": "Even strength", "default": True,
         "hint": "Equal numbers of skaters. An empty net still counts as even.",
         "manpower": sorted(EVEN_STRENGTH.manpower), "goalies": goalies},
        {"id": "pp", "label": "Power play", "hint": "A man or two up.",
         "manpower": ["PP1", "PP2"], "goalies": goalies},
        {"id": "sh", "label": "Shorthanded", "hint": "A man or two down.",
         "manpower": ["SH1", "SH2"], "goalies": goalies},
        {"id": "all", "label": "Everything", "hint": "No narrowing at all.",
         "manpower": list(ctx.MANPOWERS), "goalies": goalies},
    ]


# --- Cubes on disk ---------------------------------------------------------

def _available() -> list[dict]:
    """Every built cube under :data:`CUBE_DIR`, newest build first."""
    out: list[dict] = []
    if not CUBE_DIR.is_dir():
        return out
    for directory in sorted(CUBE_DIR.iterdir()):
        meta_path = directory / "meta.json"
        if not directory.is_dir() or not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as problem:
            _log.warning("cube %s: unreadable meta.json (%s)", directory.name,
                         problem)
            continue
        out.append({"name": directory.name, "games": len(meta.get("games", [])),
                    "built": meta.get("built", ""),
                    "lanes": meta.get("lanes", 0),
                    "has_teams": bool(meta.get("team_count_rows"))})
    return sorted(out, key=lambda c: c["built"], reverse=True)


def _load(name: str):
    """A cube by directory name, cached. None when there is no such cube."""
    if not _is_safe_segment(name):
        return None
    if name in _cube_cache:
        _cube_cache.move_to_end(name)
        return _cube_cache[name]
    directory = CUBE_DIR / name
    if not (directory / "meta.json").is_file():
        return None
    from hockey.metrics.cube import Cube
    cube = Cube.load(directory)
    _cube_cache[name] = cube
    while len(_cube_cache) > CUBE_CACHE_SIZE:
        _cube_cache.popitem(last=False)
    return cube


# --- The page --------------------------------------------------------------

@cube_bp.route("/explore")
def explore():
    return render_template("explore.html", cubes=_available(),
                           cube_dir=str(CUBE_DIR))


@cube_bp.route("/api/explore/cubes")
def api_cubes():
    return jsonify({"cubes": _available(), "dir": str(CUBE_DIR)})


@cube_bp.route("/api/explore/tree")
def api_tree():
    """The metric tree with its descriptions. Independent of any cube."""
    from hockey.derive import lane_docs
    from hockey.derive import metric_catalog as catalog

    sections = []
    for section in catalog.TREE:
        populations = []
        for pop in section.populations:
            groups = [{
                "group": group,
                "description": lane_docs.for_group(pop.label, group),
                "items": [{"key": lane.key, "item": lane.item,
                           "description": lane.description,
                           "described": lane.description_source}
                          for lane in lanes],
            } for group, lanes in pop.groups]
            populations.append({
                "label": pop.label,
                "description": lane_docs.for_population(pop.label),
                "all": {"key": pop.all_lane.key, "item": pop.all_lane.item,
                        "description": pop.all_lane.description,
                        "described": pop.all_lane.description_source},
                "groups": groups})
        sections.append({"section": section.label, "populations": populations})
    return jsonify({"sections": sections, "lanes": len(catalog.LANES),
                    "coverage": lane_docs.coverage()["missing"]})


@cube_bp.route("/api/explore/cubes/<name>/options")
def api_options(name: str):
    """What this cube can be narrowed BY: its games, players, teams, periods."""
    from hockey.derive import context_filter as ctx

    cube = _load(name)
    if cube is None:
        return jsonify({"error": f"no cube named {name!r}"}), 404

    team_names = cube.team_names
    # Which two benches each game had, for a cube saved before games.csv.
    by_game: dict[int, list[int]] = {}
    if len(cube.team_toi):
        for game_id, team_id in (cube.team_toi[["game_id", "team_id"]]
                                 .drop_duplicates().itertuples(index=False)):
            by_game.setdefault(int(game_id), []).append(int(team_id))

    schedule = cube.game_table()
    if len(schedule):
        # In the order they were played, which is the order a picker wants:
        # "the first ten games" is then the first ten rows.
        games = [{"id": int(row.game_id),
                  "label": f"{row.date}  {row.label}"
                           + (f"  {row.score}" if row.score else ""),
                  "date": row.date}
                 for row in schedule.itertuples(index=False)]
    else:
        games = [{"id": game_id, "date": "",
                  "label": " – ".join(team_names.get(t, str(t))
                                      for t in sorted(by_game.get(game_id, [])))
                           or str(game_id)}
                 for game_id in cube.games]

    players = [{"id": int(row.player_id), "label": row.name,
                "position": row.position or ""}
               for row in cube.players.itertuples(index=False)]
    present = sorted({team for benches in by_game.values() for team in benches})
    teams = [{"id": team, "label": team_names.get(team, str(team))}
             for team in present]
    return jsonify({
        "name": name, "games": games, "players": players, "teams": teams,
        "presets": _presets(),
        "manpower": [{"id": m, "label": _MANPOWER_LABELS.get(m, m)}
                     for m in ctx.MANPOWERS],
        "periods": [{"id": p, "label": _PERIOD_LABELS.get(p, p)}
                    for p in ctx.PERIODS[1:]],
        "goalies": [{"id": g, "label": g} for g in ctx.GOALIE_SITUATIONS],
    })


@cube_bp.route("/api/explore/cubes/<name>/query", methods=["POST"])
def api_query(name: str):
    """A selection in, a table out. The only endpoint the table pane calls."""
    from hockey.derive import metric_catalog as catalog

    cube = _load(name)
    if cube is None:
        return jsonify({"error": f"no cube named {name!r}"}), 404

    selection = request.get_json(silent=True) or {}
    lanes = [key for key in (selection.get("lanes") or [])
             if key in catalog.BY_KEY]
    if not lanes:
        return jsonify({"error": "pick at least one metric"}), 400
    attribution = "team" if selection.get("attribution") == "team" else "player"
    side = selection.get("side") or "for"
    if side not in ("for", "against", "credited"):
        return jsonify({"error": f"unknown side {side!r}"}), 400
    if attribution == "team" and side == "credited":
        return jsonify({"error": "'He did it' asks about a player; pick for or "
                                 "against for a team"}), 400
    value = "xg" if selection.get("value") == "xg" else "n"
    per60 = bool(selection.get("per60"))

    def chosen(key: str):
        """An empty selection means every value, which slice() spells None."""
        values = selection.get(key)
        return list(values) if values else None

    sliced = cube.slice(games=chosen("games"), players=chosen("players"),
                        teams=chosen("teams"), periods=chosen("periods"),
                        manpower=chosen("manpower"), goalies=chosen("goalies"))

    team_names = cube.team_names
    if attribution == "player":
        sample = sliced.summary()
        wide = sliced.wide(side=side, value=value, per60=per60)
        identity = [("Player", lambda row: row["name"]),
                    ("Team", lambda row: team_names.get(row["team_id"],
                                                        str(row["team_id"]))),
                    ("Pos", lambda row: row["position"] or "")]
    else:
        sample = sliced.team_summary()
        wide = sliced.team_wide(side=side, value=value, per60=per60,
                               labels=False)
        identity = [("Team", lambda row: row["name"])]

    # A lane nobody triggered has no column; it is a zero, not a blank.
    for key in lanes:
        if key not in wide.columns:
            wide[key] = 0.0

    rows = []
    for player_id, entry in sample.iterrows():
        values = wide.loc[player_id] if player_id in wide.index else None
        row = [cell(entry) for _, cell in identity]
        # The sample, always: games, total ice time, and ice time per game --
        # the three numbers that say whether a rate beside them means anything.
        row += [int(entry["games"]), round(float(entry["minutes"]), 1),
                _mmss(entry["minutes"] / max(int(entry["games"]), 1))]
        decimals = per60 or value == "xg"
        for key in lanes:
            cell = float(values[key]) if values is not None else 0.0
            row.append(round(cell, 2) if decimals else int(round(cell)))
        rows.append(row)

    toi_heading = "TOI (min)" if attribution == "player" else "Minutes"
    columns = ([label for label, _ in identity]
               + ["GP", toi_heading, "per game"] + lanes)
    units = ("per 60 minutes of "
             + ("ice time" if attribution == "player" else "game time")
             if per60 else ("expected goals" if value == "xg" else "events"))
    return jsonify({
        "columns": columns, "rows": rows, "units": units,
        # Where the metrics start: everything before it is who and how much
        # sample, which the page greys rather than reading as a metric.
        "lead": len(columns) - len(lanes),
        "games": len(sliced.games),
        "note": _describe(selection, attribution, side, sliced),
    })


def _mmss(minutes: float) -> str:
    """Minutes as m:ss, the way the PDF reports print TOI per game."""
    seconds = int(round(minutes * 60))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _describe(selection: dict, attribution: str, side: str, sliced) -> str:
    """One line saying what the table is, in the page's own words."""
    if attribution == "player":
        whose = {"for": "Their own team's events while they were on the ice",
                 "against": "The opponent's events while they were on the ice",
                 "credited": "Events the player was credited with"}[side]
        minutes = f"{sliced.minutes:.0f} player-minutes"
    else:
        whose = {"for": "The team's own events, counted once each",
                 "against": "The opponent's events, counted once each"}[side]
        minutes = f"{sliced.team_minutes:.0f} minutes of hockey"
    manpower = selection.get("manpower") or []
    situation = (", ".join(_MANPOWER_LABELS.get(m, m) for m in manpower)
                 if manpower else "every situation")
    return (f"{whose}. {situation}. {len(sliced.games)} game(s), "
            f"{minutes} in the selection.")


if __name__ == "__main__":
    # The explorer on its own, for when you want the page and not the rest of
    # the site: run this file. It is the same blueprint app.py registers -- so
    # `python app.py` already serves /explore -- only a smaller front door, on
    # its own port so both can run at once.
    import logging
    from flask import Flask, redirect

    logging.basicConfig(level=logging.INFO)
    standalone = Flask(__name__, template_folder="templates")
    standalone.register_blueprint(cube_bp)
    standalone.add_url_rule("/", "home", lambda: redirect("/explore"))

    print(f"cubes: {CUBE_DIR.resolve()}  ({len(_available())} built)")
    print("open  http://127.0.0.1:8001/explore")
    standalone.run(debug=True, host="0.0.0.0", port=8001)
