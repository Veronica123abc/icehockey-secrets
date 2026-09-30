#!/usr/bin/python
"""Validate our metrics against the supplier's own published numbers.

``golden.py`` freezes what we compute so a refactor cannot change it silently.
This answers the other question: are the frozen numbers RIGHT. The supplier
publishes the same statistics we derive, so they can be compared player by
player -- and where they disagree, one of the two is wrong.

FAST BECAUSE IT IS FETCHED ONCE. The v3 metrics endpoint answers a whole
league season in one call (435 skaters, ~5s), and that answer is written to
``supplier_cache/`` and read from disk afterwards, so re-validating after a
code change costs nothing and needs no network. ``--refresh`` re-fetches; a
season that is over never needs it twice. This is the point of the module:
the supplier's API is too slow to sit inside a development loop, so it is
pulled out of the loop and turned into a local fixture.

    python -m hockey.regression.supplier --league 17 --season 20252026
    python -m hockey.regression.supplier --league 17 --season 20252026 --refresh
    python -m hockey.regression.supplier --mapping credited --worst 15

WHAT MAPS TO WHAT is declared in :data:`WOI` and :data:`CREDITED` as a list of
:class:`Check`, one per column the two sides have in common. Each names the
supplier's ``metricKey``, the topic it lives in, and the :class:`Column` of
ours that should equal it. Nothing else in the file knows any metric's name.

THE SITUATION HAS TO MATCH ON BOTH SIDES. ``mps=["ES"]`` on the wire and
:data:`~hockey.metrics.on_ice.EVEN_STRENGTH` here are the same selection: the
supplier's ES covers 3v3, 4v4 and 5v5 and says nothing about goalies, which is
why our context admits every goalie situation. Checked rather than assumed --
with the narrower ``ctx.DEFAULT`` the shot counts come out ~3% low.

TOI IS NOT PUBLISHED BY THESE ENDPOINTS, so only counts are compared. That is
the stronger half anyway: a rate is a count over ice time, the ice time comes
from the shift table the supplier also gave us, and a count is exact.

A COUNT THAT IS OFF BY ONE IS NOT NECESSARILY A BUG. An event at the instant a
shift ends is on one side of the boundary for us and can be on the other for
them; those cancel in aggregate and show up as a symmetric spread of +-1. The
report prints that spread separately from real disagreement for exactly this
reason.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from hockey.metrics.on_ice import (AGAINST, Column, ColumnSet, CREDITED as _CRED,
                                   EVEN_STRENGTH, FOR, open_connection,
                                   player_rows)

SNAPSHOT_DIR = Path(__file__).resolve().parent / "supplier_cache"

#: Manpower filter on the wire. The supplier's "ES" is equal skaters at any
#: count, which is what EVEN_STRENGTH means here.
ES = ("ES",)


@dataclass(frozen=True)
class Check:
    """One comparable number: the supplier's name for it, and ours.

    ``metric`` is the supplier's ``metricKey`` exactly as the topic definition
    spells it -- run with ``--topics`` to list them. ``column`` is the
    :class:`~hockey.metrics.on_ice.Column` that should equal it.
    """
    metric: str
    column: Column
    topic: int
    scope: str = "skater"
    collection: str = "advancedStats"

    @property
    def source(self) -> tuple[str, str, int]:
        """The one fetch this check reads from."""
        return (self.collection, self.scope, self.topic)


def _woi(heading: str, lanes, side: str, weight: str | None = None) -> Column:
    return Column(heading, lanes, side, weight=weight, rate=False)


#: On-ice attribution -- what ``shooting_player_woi.py`` reports. Topic 32
#: ("All Plays") is where the supplier keeps its WOI metrics.
#:
#: Inner-slot is the one that needs two lanes ANDed: the supplier publishes
#: inner-slot shots ON NET, where our catalog keeps location and result in
#: separate groups, so the column asks for both.
WOI: tuple[Check, ...] = (
    Check("Total Goals For WOI",               _woi("GF",   "Goals · All",    FOR), 32),
    Check("Total Goals Against WOI",           _woi("GA",   "Goals · All",    AGAINST), 32),
    Check("Expected Goals For WOI",            _woi("xGF",  "Shots · All",    FOR,     "xg_official"), 32),
    Check("Expected Goals Against WOI",        _woi("xGA",  "Shots · All",    AGAINST, "xg_official"), 32),
    Check("Shot Attempts For WOI",             _woi("SAF",  "Shots · All",    FOR), 32),
    Check("Shot Attempts Against WOI",         _woi("SAA",  "Shots · All",    AGAINST), 32),
    Check("Shots On Net For WOI",              _woi("SOGF", "Shots · On Net", FOR), 32),
    Check("Shots On Net Against WOI",          _woi("SOGA", "Shots · On Net", AGAINST), 32),
    Check("Inner Slot Shots On Net For WOI",
          _woi("ISF", ("Shots · Inner Slot", "Shots · On Net"), FOR), 32),
    Check("Inner Slot Shots On Net Against WOI",
          _woi("ISA", ("Shots · Inner Slot", "Shots · On Net"), AGAINST), 32),
)

#: Credited attribution -- what ``shooting_player.py`` reports. The supplier
#: keeps these in the shooting topics rather than in the WOI one, and does not
#: suffix them, because a metric with no suffix is the player's own.
CREDITED: tuple[Check, ...] = (
    Check("Total Shots Taken",            _woi("SA",   "Shots · All",    _CRED), 2),
    Check("Total Successful Shots Taken", _woi("SOG",  "Shots · On Net", _CRED), 2),
    Check("Total Regular Goals",          _woi("G",    "Goals · All",    _CRED), 2),
    Check("Total Shot From Slot Attempts",_woi("Slot", "Shots · Slot",   _CRED), 2),
    Check("Expected Goals",               _woi("xG",   "Shots · All",    _CRED, "xg_official"), 7),
)

MAPPINGS = {"woi": WOI, "credited": CREDITED}


# --- The supplier's side, fetched once -------------------------------------

def _api():
    from hockey.data_collection.sportlogiq import SportlogiqV3
    return SportlogiqV3()


def season_id(season: str, api=None) -> str:
    """The v3 numeric season id for a name like ``"20252026"``.

    The v3 API keys seasons by an opaque id where the rest of this repo keys
    them by the name the v1 API uses, so every call here has to translate.
    """
    api = api or _api()
    for row in api.get("/api/v3/seasons", []):
        if str(row.get("name")) == str(season):
            return str(row["id"])
    raise KeyError(f"no v3 season id for {season!r}")


def _snapshot_path(league: int, season: str, stage: str, collection: str,
                   scope: str, topic: int, mps: Sequence[str]) -> Path:
    mps_part = "-".join(mps) if mps else "all"
    return SNAPSHOT_DIR / (f"{league}_{season}_{stage}_{collection}_{scope}"
                           f"_t{topic}_{mps_part}.json")


def fetch(league: int, season: str, *, stage: str = "regular",
          collection: str = "advancedStats", scope: str = "skater",
          topic: int = 32, mps: Sequence[str] = ES,
          refresh: bool = False, quiet: bool = False) -> list[dict]:
    """The supplier's rows for one topic, from disk or from the API.

    One row per player (or team), keyed by ``playerid`` / ``teamid``, with one
    field per metric of the topic. Written to :data:`SNAPSHOT_DIR` on the first
    call so every later one is free.
    """
    path = _snapshot_path(league, season, stage, collection, scope, topic, mps)
    if path.exists() and not refresh:
        return json.loads(path.read_text())

    from hockey.data_collection.sportlogiq import QueryFilters
    api = _api()
    rows = api.metrics.topic_values(
        league, season_id(season, api), stage, collection, scope, topic,
        aggregationtype="total",
        filters=QueryFilters(mps=list(mps)) if mps else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    if not quiet:
        print(f"  fetched {len(rows)} {scope} rows -> {path.name}")
    return rows


def topics(league: int, season: str, *, collection: str = "advancedStats",
           scope: str = "skater") -> None:
    """Print the supplier's topics and metric keys -- how to extend a mapping."""
    api = _api()
    sid = season_id(season, api)
    for topic in api.metrics.topics(league, sid, collection, scope):
        print(f"\n=== topic {topic['id']}: {topic['label']} ===")
        detail = api.metrics.topic_metrics(league, sid, collection, scope,
                                           topic["id"])

        def walk(nodes, depth=1):
            for node in nodes:
                if node.get("type") == "group":
                    print("  " * depth + f"[{node.get('label')}]")
                    walk(node.get("metrics", ()), depth + 1)
                else:
                    print("  " * depth + str(node.get("metricKey")))
        walk(detail.get("metrics", ()))


# --- Comparing --------------------------------------------------------------

@dataclass
class Line:
    """One check's result over every player."""
    check: Check
    ours: float = 0.0
    theirs: float = 0.0
    compared: int = 0
    exact: int = 0
    within_one: int = 0
    worst: list = None            # (delta, player_id, name, ours, theirs)

    @property
    def agreement(self) -> float:
        return self.exact / self.compared if self.compared else 0.0

    @property
    def ratio(self) -> float:
        return self.ours / self.theirs if self.theirs else 0.0


def compare(league: int = 17, season: str = "20252026", *,
            mapping: Iterable[Check] = WOI, stage: str = "regular",
            mps: Sequence[str] = ES, context=EVEN_STRENGTH,
            players: Iterable[int] | None = None, conn=None,
            refresh: bool = False, quiet: bool = False,
            ) -> tuple[list[Line], dict]:
    """Our numbers against the supplier's, one line per check.

    ``players`` limits the comparison; None compares every player the supplier
    lists. Returns the lines and a summary dict.

    A metric a column is weighted on (xG) is compared with a small tolerance
    because it is a float sum; a count is compared exactly.
    """
    checks = list(mapping)
    opened = conn is None
    conn = conn or open_connection()
    try:
        # The supplier's side: one fetch per distinct topic, cached on disk.
        rows_by_source: dict[tuple, dict[int, dict]] = {}
        for source in dict.fromkeys(check.source for check in checks):
            collection, scope, topic = source
            rows = fetch(league, season, stage=stage, collection=collection,
                         scope=scope, topic=topic, mps=mps, refresh=refresh,
                         quiet=quiet)
            key = "playerid" if scope in ("skater", "goalie") else "teamid"
            rows_by_source[source] = {int(r[key]): r for r in rows if r.get(key)}

        listed = sorted({pid for rows in rows_by_source.values() for pid in rows})
        wanted = ([int(p) for p in players] if players is not None else listed)

        # Our side: one pass over the games, every column at once.
        columns = ColumnSet(check.column for check in checks)
        ours, missing = player_rows(conn, wanted, league, season,
                                    columns=columns, context=context,
                                    stage=stage)
    finally:
        if opened:
            conn.close()

    mine = {row.player_id: row for row in ours}
    lines = []
    for check in checks:
        theirs = rows_by_source[check.source]
        tol = 0.05 if check.column.weight else 0.5
        line = Line(check=check, worst=[])
        for pid, row in mine.items():
            value = theirs.get(pid, {}).get(check.metric)
            if value is None:
                continue
            got = row.totals[check.column.key]
            line.compared += 1
            line.ours += got
            line.theirs += float(value)
            delta = got - float(value)
            if abs(delta) < tol:
                line.exact += 1
            if abs(delta) <= 1.0 + tol:
                line.within_one += 1
            else:
                line.worst.append((delta, pid, row.name, got, float(value)))
        line.worst.sort(key=lambda item: -abs(item[0]))
        lines.append(line)

    summary = {
        "league": league, "season": season, "stage": stage,
        "situation": " · ".join(context.describe()) if context else "all",
        "supplier_rows": len(listed), "our_rows": len(mine),
        "not_listed_by_supplier": sorted(set(mine) - set(listed)),
        "no_row_from_us": sorted(set(wanted) - set(mine)),
        "missing": list(missing),
    }
    return lines, summary


def report(lines: Sequence[Line], summary: dict, *, worst: int = 5) -> bool:
    """Print the comparison. Returns True when every count agrees exactly."""
    print(f"\nLeague {summary['league']} · {summary['season']} · "
          f"{summary['stage']} · {summary['situation']}")
    print(f"{summary['supplier_rows']} players published, "
          f"{summary['our_rows']} computed here"
          + (f", {len(summary['no_row_from_us'])} with no line from us"
             if summary['no_row_from_us'] else ""))

    head = (f"\n{'metric':<40}{'n':>5}{'exact':>7}{'±1':>7}{'off':>5}"
            f"{'ours':>12}{'supplier':>12}{'ratio':>8}")
    print(head); print("-" * len(head.strip("\n")))
    clean = True
    for line in lines:
        off = line.compared - line.within_one
        clean = clean and line.exact == line.compared
        print(f"{line.check.metric:<40}{line.compared:>5}{line.exact:>7}"
              f"{line.within_one:>7}{off:>5}{line.ours:>12,.1f}"
              f"{line.theirs:>12,.1f}{line.ratio:>8.4f}")

    for line in lines:
        if not line.worst:
            continue
        print(f"\n  {line.check.metric} — {len(line.worst)} beyond ±1:")
        for delta, pid, name, got, theirs in line.worst[:worst]:
            print(f"    {name[:24]:<25} {pid:<8} ours {got:9,.2f}  "
                  f"supplier {theirs:9,.2f}  delta {delta:+,.2f}")
    return clean


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", type=int, default=17)
    parser.add_argument("--season", default="20252026")
    parser.add_argument("--stage", default="regular")
    parser.add_argument("--mapping", choices=sorted(MAPPINGS), default="woi")
    parser.add_argument("--players", type=int, nargs="*", default=None,
                        help="limit to these player sl_ids")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch from the API instead of reading the cache")
    parser.add_argument("--worst", type=int, default=5,
                        help="how many disagreements to name per metric")
    parser.add_argument("--topics", action="store_true",
                        help="list the supplier's topics and metric keys, then exit")
    args = parser.parse_args()

    if args.topics:
        topics(args.league, args.season)
        return 0

    lines, summary = compare(args.league, args.season,
                             mapping=MAPPINGS[args.mapping],
                             stage=args.stage, players=args.players,
                             refresh=args.refresh)
    return 0 if report(lines, summary, worst=args.worst) else 1


if __name__ == "__main__":
    raise SystemExit(main())
