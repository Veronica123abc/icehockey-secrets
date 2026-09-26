#!/usr/bin/env python
"""Build Sportlogiq-style player cards for a league season.

    python examples/player_cards.py --teamid 1
    python examples/player_cards.py --teamid 1 --position D
    python examples/player_cards.py --teamid 1 --out cards.csv

The metric list, labels, ordering and formatting come from the ``playercard``
report definition::

    GET /api/v3/leagues/{leagueId}/season/{seasonId}/reportmetricdefs/playercard

which defines three sets — ``playerCardMetricsForwards`` (21 metrics),
``playerCardMetricsDefencemen`` (20) and ``playerCardMetricsGoalies`` (11).

Where the numbers come from
---------------------------
The v3 API has no "report values" endpoint: ``reportmetricdefs`` tells you what
a card *contains*, and ``/metrics/reports/metricevents`` returns the underlying
events, but nothing serves aggregated report values. Passing the report's set
ids to ``/metrics/setcollections/topicvalues`` returns HTTP 500 — those ids
live in a different id space from metric set collection topics.

So this script resolves each metric by name against the metric set collections
(``advancedStats``, ``linesAndPairs``, ``scouting``, ``faceOffs``), which do
serve aggregated per-player values. Each card metric carries its own
``aggregation``, ``averageGranularity`` and ``manpowerSituation``, so metrics
are grouped into one query per distinct combination.

About two thirds of card metrics resolve directly by name. The rest are ratios
and percentages the web app computes client-side; those are derived here from
available inputs (``DERIVED_SHARES``, ``DERIVED_SUMS``, ``FROM_SUMMARY``).

One metric has no source at all — ``Strength of Teammates Contribution
Percentage``. ``linesAndPairs`` offers ``Strength of Teammates``, but that is a
raw rating rather than a contribution share, so it is listed in ``UNAVAILABLE``
and reported as missing rather than silently substituted.

The CSV is the union of all three card layouts, so goalie columns are empty on
skater rows and vice versa. Values are written unformatted for downstream use;
the printed cards apply each metric's ``displayFormat``.

Building the name->topic index costs ~60 requests, so it is cached in
``examples/.metric_index.json`` (keyed by league and season). Delete that file
to rebuild.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hockey.data_collection.sportlogiq import (
    QueryFilters,
    SportlogiqError,
    SportlogiqV3,
)

CACHE = Path(__file__).resolve().parent / ".metric_index.json"

COLLECTION_TYPES = ["advancedStats", "linesAndPairs", "scouting", "faceOffs"]

#: report manpowerSituation -> the mps filter value
MPS = {
    "all": None,
    "evenStrength": "ES",
    "powerPlay": "PP",
    "shortHanded": "SH",
}

#: Share metrics the collections do not serve directly. ``for``/``against``
#: pairs become ``for / (for + against)``; ``of`` pairs become ``part / whole``.
DERIVED_SHARES = {
    "Corsi Ratio": ("Shot Attempts For WOI", "Shot Attempts Against WOI", "vs"),
    "Expected Goals Corsi Ratio": (
        "Expected Goals For WOI", "Expected Goals Against WOI", "vs",
    ),
    "Inner Slot Shots On Net Corsi Ratio": (
        "Inner Slot Shots On Net For WOI", "Inner Slot Shots On Net Against WOI", "vs",
    ),
    # Face-off percentages are wins over face-offs *taken*, not wins vs losses:
    # the API exposes no "losses" metric, and taken already includes them.
    "OZ Face Off Win Percentage": ("OZ Face-Off Wins", "Total OZ Face-Off Taken", "of"),
    "DZ Face Off Win Percentage": ("DZ Face-Off Wins", "Total DZ Face-Off Taken", "of"),
}
DERIVED_SUMS = {"Total Points": ("Total Goals", "Total Assists")}

#: Card metrics served by the seasonSummaries block instead of a topic.
#: ``ozStart`` arrives as a fraction, so it is scaled to a percentage.
FROM_SUMMARY = {"OZ Starts Percentage": ("ozStart", 100.0)}

#: Card metrics with no available source. Listed explicitly so the script can
#: say so rather than silently substituting something close but different.
#: "Strength of Teammates" exists in linesAndPairs, but it is a raw rating, not
#: the contribution percentage the card asks for.
UNAVAILABLE = {"Strength of Teammates Contribution Percentage"}

SET_FOR_POSITION = {
    "F": "playerCardMetricsForwards",
    "D": "playerCardMetricsDefencemen",
    "G": "playerCardMetricsGoalies",
}


# ---------------------------------------------------------------- index ----


def _metric_names(node, out: set[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "metric" and node.get("baseMetric"):
            out.add(node["baseMetric"])
        for value in node.values():
            _metric_names(value, out)
    elif isinstance(node, list):
        for value in node:
            _metric_names(value, out)


def build_index(api: SportlogiqV3, league_id, season_id, verbose=True) -> dict:
    """Map scope -> baseMetric name -> [collection_type, topic_id].

    The index must be keyed by scope. Many metric names exist in both the
    skater and goalie collections, and querying a skater topic for a goalie's
    id simply returns no row — so a scope-blind index silently blanks the
    entire goalie card.

    Within a scope the first topic serving a metric wins, which is enough: a
    topic's values payload returns every metric that topic contains.
    """
    key = f"{league_id}:{season_id}:v2"
    if CACHE.exists():
        cached = json.loads(CACHE.read_text())
        if cached.get("_key") == key:
            return cached["index"]

    index: dict[str, dict[str, list]] = {"skater": {}, "goalie": {}}
    for collection in COLLECTION_TYPES:
        for scope in ("skater", "goalie"):
            try:
                topics = api.metrics.topics(league_id, season_id, collection, scope)
            except SportlogiqError:
                continue
            for topic in topics:
                try:
                    detail = api.metrics.topic_metrics(
                        league_id, season_id, collection, scope, topic["id"]
                    )
                except SportlogiqError:
                    continue
                names: set[str] = set()
                _metric_names(detail, names)
                for name in names:
                    index[scope].setdefault(name, [collection, topic["id"]])
            if verbose:
                print(f"  indexed {collection}/{scope}: {len(topics)} topics")

    CACHE.write_text(json.dumps({"_key": key, "index": index}))
    return index


# --------------------------------------------------------------- fetching ---


def fetch_values(
    api: SportlogiqV3,
    league_id,
    season_id,
    season_stage,
    metrics: list[dict],
    index: dict,
    scope: str,
    team_id=None,
    verbose=True,
) -> tuple[dict, list[str]]:
    """Fetch every metric a card needs. Returns (per-player values, unresolved).

    Metrics are grouped by (topic, manpower, aggregation, granularity) so each
    distinct query runs once rather than once per metric.
    """
    groups: dict[tuple, set[str]] = defaultdict(set)
    unresolved: list[str] = []
    for metric in metrics:
        base_metric = metric["baseMetric"]
        if base_metric in FROM_SUMMARY:
            continue
        if base_metric in UNAVAILABLE:
            if base_metric not in unresolved:
                unresolved.append(base_metric)
            continue
        share = DERIVED_SHARES.get(base_metric)
        bases = share[:2] if share else DERIVED_SUMS.get(base_metric, (base_metric,))
        for base in bases:
            where = index.get(scope, {}).get(base)
            if not where:
                if base not in unresolved:
                    unresolved.append(base)
                continue
            key = (
                tuple(where),
                metric["manpowerSituation"],
                metric["aggregation"],
                # Granularity only applies to averages; normalise it away for
                # sums so the fetch key matches the one resolve() looks up.
                metric["averageGranularity"]
                if metric["aggregation"] == "average"
                else None,
            )
            groups[key].add(base)

    values: dict[str, dict] = defaultdict(dict)
    for (where, manpower, aggregation, granularity), bases in groups.items():
        collection, topic_id = where
        mps = MPS.get(manpower)
        filters = QueryFilters(teamid=[team_id] if team_id else [])
        if mps:
            filters.mps = [mps]
        try:
            rows = api.metrics.topic_values(
                league_id, season_id, season_stage, collection, scope, topic_id,
                aggregationtype=aggregation,
                averagegranularity=granularity,
                filters=filters,
            )
        except SportlogiqError as exc:
            if verbose:
                print(f"  ! {collection}/{topic_id} {manpower}: HTTP {exc.status}")
            continue

        for row in rows:
            player_id = row.get("playerid")
            if not player_id:
                continue
            for base in bases:
                if base in row:
                    # Aggregation belongs in the key: the same baseMetric is
                    # fetched both as a raw count and as a per-60 rate (once as
                    # a card cell, once as a ratio input). Without it, one
                    # silently overwrites the other.
                    key = (base, manpower, aggregation, granularity)
                    values[player_id][key] = row[base]
        if verbose:
            print(
                f"  {collection}/{topic_id:>3} {manpower:<13} "
                f"{aggregation}/{granularity}: {len(rows)} players, {len(bases)} metrics"
            )

    return values, unresolved


def resolve(metric: dict, player_values: dict, summary: dict | None) -> float | None:
    """Compute one card cell for one player."""
    base = metric["baseMetric"]
    manpower = metric["manpowerSituation"]
    aggregation = metric["aggregation"]
    granularity = metric["averageGranularity"] if aggregation == "average" else None

    def look(name):
        return player_values.get((name, manpower, aggregation, granularity))

    if base in UNAVAILABLE:
        return None

    if base in FROM_SUMMARY:
        field, scale = FROM_SUMMARY[base]
        raw = (summary or {}).get(field)
        return None if raw is None else raw * scale

    if base in DERIVED_SHARES:
        first_name, second_name, kind = DERIVED_SHARES[base]
        first, second = look(first_name), look(second_name)
        if first is None or second is None:
            return None
        whole = (first + second) if kind == "vs" else second
        return 100 * first / whole if whole else None

    if base in DERIVED_SUMS:
        parts = [look(n) for n in DERIVED_SUMS[base]]
        if any(p is None for p in parts):
            return None
        return sum(parts)

    return look(base)


def fmt(value, display_format: str) -> str:
    if value is None:
        return "-"
    if display_format == "metric":
        # Counts (sum aggregation) arrive integral; rates keep two decimals.
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    if display_format == "rate":
        return f"{value:.1f}%"
    return f"{value:.2f}"


# ------------------------------------------------------------------ main ----


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leagueid", default=1)
    parser.add_argument("--seasonid", default=12)
    parser.add_argument(
        "--seasonstage", default="regular", choices=["preseason", "regular", "playoffs"]
    )
    parser.add_argument("--teamid", default=1, help="team to build cards for")
    parser.add_argument(
        "--position", choices=["F", "D", "G"], help="only this position group"
    )
    parser.add_argument("--limit", type=int, default=5, help="max cards to print")
    parser.add_argument("--out", type=Path, help="write all cards to this CSV")
    args = parser.parse_args()

    api = SportlogiqV3()

    defs = api.metrics.league_report_defs(args.leagueid, args.seasonid, "playercard")
    sets = {s["name"]: s for s in defs["metricSets"]}

    print("Indexing metric collections (cached after first run)...")
    index = build_index(api, args.leagueid, args.seasonid)
    print(f"  {len(index['skater'])} skater / {len(index['goalie'])} goalie metrics indexed\n")

    # Positions come from a game roster; the players endpoint does not carry them.
    games = api.games.list(
        teamid=[args.teamid], seasonid=[args.seasonid], seasonstage=[args.seasonstage]
    )["games"]
    if not games:
        print("No games found for that team/season/stage.", file=sys.stderr)
        return 1
    roster = api.games.rosters(games[-1]["id"])
    positions: dict[str, str] = {}
    for team_id, team in (roster.get("teams") or {}).items():
        if str(team_id) != str(args.teamid):
            continue
        for player in team.get("players") or []:
            positions[player["id"]] = player.get("primaryPosition") or "F"

    names = {
        p["id"]: f"{p.get('firstName','')} {p.get('lastName','')}".strip()
        for p in api.players.for_team(args.teamid, args.seasonid, [args.seasonstage])
    }

    summaries_raw = api.players.search(
        teamid=[args.teamid],
        seasonid=[args.seasonid],
        seasonstage=[args.seasonstage],
        withseasonsummaries=True,
    ).get("seasonSummaries") or {}
    summaries: dict[str, dict] = {}
    for player_id, entries in summaries_raw.items():
        for entry in entries if isinstance(entries, list) else [entries]:
            if (
                str(entry.get("teamId")) == str(args.teamid)
                and str(entry.get("seasonId")) == str(args.seasonid)
                and entry.get("seasonStage") == args.seasonstage
            ):
                summaries[player_id] = entry

    wanted = [args.position] if args.position else ["F", "D", "G"]
    all_rows = []

    for position in wanted:
        metric_set = sets[SET_FOR_POSITION[position]]
        metrics = sorted(
            metric_set["metrics"], key=lambda m: (m["reportPart"], m["displayOrder"])
        )
        group = [p for p, pos in positions.items() if pos == position]
        if not group:
            continue

        print(f"=== {metric_set['label']} — {len(group)} players ===")
        values, unresolved = fetch_values(
            api, args.leagueid, args.seasonid, args.seasonstage,
            metrics, index, "goalie" if position == "G" else "skater",
            team_id=args.teamid,
        )
        if unresolved:
            print(f"  unresolved metrics: {', '.join(unresolved)}")
        print()

        ranked = sorted(
            group, key=lambda p: -(summaries.get(p, {}).get("gamesPlayed") or 0)
        )
        for shown, player_id in enumerate(ranked):
            card = {
                "playerId": player_id,
                "name": names.get(player_id, "?"),
                "position": position,
                "gamesPlayed": (summaries.get(player_id) or {}).get("gamesPlayed"),
            }
            for metric in metrics:
                card[metric["label"]] = resolve(
                    metric, values.get(player_id, {}), summaries.get(player_id)
                )
            all_rows.append(card)

            if shown < args.limit:
                print(f"  {card['name']}  ({position}, GP {card['gamesPlayed']})")
                for metric in metrics:
                    raw = card[metric["label"]]
                    print(f"     {metric['label']:<24} {fmt(raw, metric['displayFormat']):>10}")
                print()

    if args.out and all_rows:
        columns = list({k: None for row in all_rows for k in row})
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"Wrote {len(all_rows)} cards to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
