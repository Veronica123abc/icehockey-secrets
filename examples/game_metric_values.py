#!/usr/bin/env python
"""Per-player (or per-team) values of one named metric, for one game.

    python examples/game_metric_values.py 54559 "Pass to Slot Success Rate"
    python examples/game_metric_values.py 54559 "Successful Pass to Slot Attempts" --scope team
    python examples/game_metric_values.py 54559 "Pass to Slot Success Rate" --groupby period
    python examples/game_metric_values.py 54559 --search slot
    python examples/game_metric_values.py 54559 "Pass to Slot Success Rate" --out passes.csv

``main_no_cli()`` at the bottom does the same thing for one hard-coded game
and metric, with every step inline and no argparse. Swap which of the two the
``__main__`` block calls to read the flow straight through.

Given a leaf metric name — a ``metricKey`` from the metric set collections —
this fetches its value for every skater in a game, aggregated over the whole
game: all manpower situations, all periods, unless ``--groupby`` splits them.

Three things about the v3 API shape this script
-----------------------------------------------
**Values come per topic, not per metric.** There is no endpoint for a single
metric. ``.../topics/{topicId}/metricvalues`` returns every metric in the
topic as columns of one row per player, so step one is resolving a metric name
to the topic that carries it. That index costs ~40 requests per league/season
and scope, so it is cached in ``examples/.metric_topic_index.json``; pass
``--refresh`` to rebuild.

**There is no gameid filter.** ``METRIC_VALUE_FILTERS`` has no game field —
games are selected by ``from``/``to`` over *scheduled time*. Pinning both ends
to the game's own ``scheduledTime`` is not enough on its own: league 13 ran
four games at 2021-10-30T16:00:00Z, and that window alone returns 154 players.
So the request also filters to the two teams, and ``groupings=['game']`` adds
a ``gameid`` column that rows are then checked against. Either narrowing would
do; both together mean a wrong game cannot silently pass through.

**Timestamps must end in Z.** ``scheduledTime`` comes back as
``2021-10-30T16:00:00+00:00``, which the filter rejects with HTTP 400 — the
pattern in the spec allows only ``YYYY-MM-DDTHH:MM:SS[.mmm]Z``. Hence
``as_z()``.

Valid ``--groupby`` values are ``game``, ``team``, ``period``,
``manpowersituation`` and ``opposingteam``. Note that ``playerid`` is *not* a
grouping: at skater scope every row is already keyed by player. An unknown
grouping name comes back as HTTP 200 with a bare string body rather than an
error, which surfaces as a JSONDecodeError.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence, get_args

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hockey.data_collection.sportlogiq import SportlogiqV3
from hockey.data_collection.sportlogiq.enums import CollectionType
from hockey.data_collection.sportlogiq.filters import QueryFilters

INDEX_PATH = Path(__file__).with_name(".metric_topic_index.json")

#: Columns the API adds for the groupings, as opposed to metric values.
ID_COLUMNS = frozenset(
    {"playerid", "teamid", "gameid", "period", "manpowersituation", "opposingteamid"}
)

GROUPINGS = ("game", "team", "period", "manpowersituation", "opposingteam")


def as_z(timestamp: str) -> str:
    """``2021-10-30T16:00:00+00:00`` -> ``2021-10-30T16:00:00Z``.

    The only timestamp form the v3 filters accept.
    """
    return (
        datetime.fromisoformat(timestamp)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def walk_metrics(nodes: Iterable[dict]) -> Iterator[dict]:
    """Yield every non-group metric node, however deeply nested."""
    for node in nodes:
        if node["type"] == "group":
            yield from walk_metrics(node.get("metrics", ()))
        else:
            yield node


# -- metric name -> topic ---------------------------------------------------


def build_index(
    api: SportlogiqV3, league_id: str, season_id: str, scope: str
) -> dict[str, str]:
    """``{metricKey: "collectionType/topicId"}`` for one scope.

    Walks every topic of every collection type — roughly 40 requests, which is
    why callers should go through :func:`load_index`.
    """
    index: dict[str, str] = {}
    for collection_type in get_args(CollectionType):
        topics = api.metrics.topics(league_id, season_id, collection_type, scope)
        for topic in topics:
            detail = api.metrics.topic_metrics(
                league_id, season_id, collection_type, scope, topic["id"]
            )
            for metric in walk_metrics(detail["metrics"]):
                # First topic to define a name wins; duplicates across topics
                # carry the same values.
                index.setdefault(
                    metric["metricKey"], f"{collection_type}/{topic['id']}"
                )
    return index


def load_index(
    api: SportlogiqV3,
    league_id: str,
    season_id: str,
    scope: str,
    refresh: bool = False,
) -> dict[str, str]:
    """Cached :func:`build_index`, keyed by league, season and scope."""
    cache: dict[str, dict[str, str]] = {}
    if INDEX_PATH.exists():
        cache = json.loads(INDEX_PATH.read_text())

    key = f"{league_id}/{season_id}/{scope}"
    if refresh or key not in cache:
        print(f"Indexing metrics for league {league_id}, season {season_id},"
              f" scope {scope} (~40 requests)...", file=sys.stderr)
        cache[key] = build_index(api, league_id, season_id, scope)
        INDEX_PATH.write_text(json.dumps(cache, indent=1))

    return cache[key]


# -- values -----------------------------------------------------------------


def game_metric_rows(
    api: SportlogiqV3,
    game: dict,
    metric_key: str,
    index: dict[str, str],
    scope: str = "skater",
    groupby: Sequence[str] = (),
    aggregationtype: str = "total",
) -> list[dict[str, Any]]:
    """Rows carrying ``metric_key`` for one game, one row per subject.

    ``groupby`` splits each subject further (``period``,
    ``manpowersituation``, ...); ``game`` is always requested so rows can be
    checked against the game id.
    """
    if metric_key not in index:
        raise KeyError(metric_key)
    collection_type, topic_id = index[metric_key].split("/")

    groupings = ["game"] + [g for g in groupby if g != "game"]
    rows = api.metrics.topic_values(
        game["leagueId"],
        game["seasonId"],
        game["seasonStage"],
        collection_type,
        scope,
        topic_id,
        aggregationtype=aggregationtype,
        groupings=groupings,
        filters=QueryFilters(
            from_=as_z(game["scheduledTime"]),
            to=as_z(game["scheduledTime"]),
            teamid=[game["homeTeamId"], game["awayTeamId"]],
        ),
    )

    keep = [c for c in ID_COLUMNS if c != "gameid"]
    return [
        {**{c: row[c] for c in keep if c in row}, metric_key: row[metric_key]}
        for row in rows
        if str(row["gameid"]) == str(game["id"])
    ]


def player_names(api: SportlogiqV3, player_ids: Sequence[str]) -> dict[str, str]:
    """``{playerid: "First Last"}`` — one search call for the whole game."""
    if not player_ids:
        return {}
    found = api.players.search(playerid=list(player_ids)).get("players") or []
    return {
        p["id"]: f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
        for p in found
    }


def roster_teams(api: SportlogiqV3, game_id: str | int) -> dict[str, str]:
    """``{playerid: teamid}`` from the game roster."""
    teams = api.games.rosters(game_id).get("teams") or {}
    return {
        player["id"]: team_id
        for team_id, team in teams.items()
        for player in team.get("players") or []
    }


def main_no_cli() -> int:
    """The whole thing as one straight line of code, no argparse.

    Same result as::

        python examples/game_metric_values.py 54559 "Pass to Slot Success Rate"

    but with every step spelled out inline, so the shape of the solution is
    visible in one screen. Edit the four constants below to point it
    somewhere else.
    """
    GAME_ID = "54559"
    METRIC = "Pass to Slot Success Rate"
    SCOPE = "skater"
    AGGREGATION = "total"

    api = SportlogiqV3()

    # 1. The game tells us which league/season/stage to query, when it was
    #    played, and who played in it. There is no gameid filter on the metric
    #    endpoints, so all four facts are needed to isolate this one game.
    game = api.games.get(GAME_ID)["game"]
    print(f"Game {game['id']}: league {game['leagueId']}, season {game['seasonId']}"
          f" ({game['seasonStage']}), {game['scheduledTime']}")

    # 2. Values are served per topic, not per metric, so the metric name has to
    #    be resolved to the topic that carries it. Cached after the first run.
    index = load_index(api, game["leagueId"], game["seasonId"], SCOPE)
    collection_type, topic_id = index[METRIC].split("/")
    print(f"{METRIC!r} lives in {collection_type}/{SCOPE} topic {topic_id}")

    # 3. Fetch the topic's values. from/to pin the window to this game's
    #    scheduled time (as_z: the API rejects the +00:00 form), teamid narrows
    #    to the two clubs, and groupings=['game'] adds a gameid column so the
    #    rows can be checked. Leaving mps/period unset means all situations,
    #    all periods — scope but no context.
    rows = api.metrics.topic_values(
        game["leagueId"], game["seasonId"], game["seasonStage"],
        collection_type, SCOPE, topic_id,
        aggregationtype=AGGREGATION,
        groupings=["game"],
        filters=QueryFilters(
            from_=as_z(game["scheduledTime"]),
            to=as_z(game["scheduledTime"]),
            teamid=[game["homeTeamId"], game["awayTeamId"]],
        ),
    )
    print(f"{len(rows)} rows in the window, before filtering on gameid")

    # 4. Four games kicked off at the same minute in this league, so drop the
    #    rows belonging to the other three, and keep just the one column.
    values = {
        row["playerid"]: row[METRIC]
        for row in rows
        if str(row["gameid"]) == str(GAME_ID)
    }

    # 5. Cosmetic: playerid -> name, and playerid -> teamid.
    names = player_names(api, list(values))
    teams = roster_teams(api, GAME_ID)

    print(f"\n{METRIC} ({AGGREGATION}) — {len(values)} players\n")
    for player_id, value in sorted(
        values.items(), key=lambda kv: (teams.get(kv[0], ""), names.get(kv[0], ""))
    ):
        name = names.get(player_id, "")
        print(f"  {player_id:>7}  {name:<24} {teams.get(player_id, ''):>4}"
              f"   {'-' if value is None else value}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gameid", help="game id, e.g. 54559")
    parser.add_argument("metric", nargs="?", help="leaf metricKey to fetch")
    parser.add_argument(
        "--scope",
        default="skater",
        choices=["skater", "team", "goalie", "opposingteam"],
    )
    parser.add_argument(
        "--groupby",
        action="append",
        default=[],
        choices=list(GROUPINGS),
        help="split each subject further (repeatable)",
    )
    parser.add_argument(
        "--aggregationtype",
        default="total",
        choices=["total", "sum", "customsum", "average", "max"],
    )
    parser.add_argument("--search", help="list metric names containing this text")
    parser.add_argument("--refresh", action="store_true", help="rebuild the metric index")
    parser.add_argument("--out", type=Path, help="write results to this CSV")
    args = parser.parse_args()

    if not args.metric and not args.search:
        parser.error("give a metric name, or --search to find one")

    api = SportlogiqV3()
    game = api.games.get(args.gameid)["game"]
    print(
        f"Game {game['id']}: league {game['leagueId']}, season {game['seasonId']}"
        f" ({game['seasonStage']}), {game['scheduledTime']},"
        f" teams {game['homeTeamId']} vs {game['awayTeamId']}"
    )

    index = load_index(
        api, game["leagueId"], game["seasonId"], args.scope, args.refresh
    )

    if args.search:
        needle = args.search.lower()
        hits = sorted(k for k in index if needle in k.lower())
        print(f"\n{len(hits)} metric(s) matching {args.search!r} at {args.scope} scope:")
        for name in hits:
            print(f"  {name}   [{index[name]}]")
        if not args.metric:
            return 0

    try:
        rows = game_metric_rows(
            api, game, args.metric, index, args.scope, args.groupby,
            args.aggregationtype,
        )
    except KeyError:
        print(f"\nNo metric named {args.metric!r} at {args.scope} scope."
              f" Try --search.", file=sys.stderr)
        return 1

    if "playerid" in (rows[0] if rows else {}):
        names = player_names(api, [r["playerid"] for r in rows])
        teams = roster_teams(api, game["id"])
        for row in rows:
            row["name"] = names.get(row["playerid"], "")
            row["teamid"] = teams.get(row["playerid"], "")

    extras = [g for g in args.groupby if g != "game"]
    columns = (
        ["playerid", "name", "teamid"] if "playerid" in (rows[0] if rows else {})
        else ["teamid"]
    ) + [c for c in extras if c in (rows[0] if rows else {})] + [args.metric]

    print(f"\n{args.metric}  ({index[args.metric]}, {args.aggregationtype})")
    print(f"{len(rows)} row(s)\n")
    for row in sorted(rows, key=lambda r: (r.get("teamid", ""), r.get("name", ""))):
        cells = "  ".join(f"{str(row.get(c, '')):<22}" for c in columns[:-1])
        value = row[args.metric]
        print(f"  {cells}  {'-' if value is None else value}")

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {args.out}")

    return 0
def test():
    GAME_ID = "54559"
    METRIC = "Pass to Slot Success Rate"
    SCOPE = "skater"
    AGGREGATION = "total"
    LEAGUE_ID = '13'
    SEASON_ID = '12'
    SEASON_STAGE = 'regular'
    COLLECTION_TYPE = "advancedStats"
    COLLECTION_SCOPE = "team"
    TOPIC_ID = '29'
    TOPIC_ID = '1'
    #METRIC = 'Total Shot From Slot Attempts'
    METRIC = 'Total Shots From Inner Slot On Net Against'
    METRIC = 'Scoring Chances Off-the-Rush'
    # METRIC = "All Dump In Attempts"
    api = SportlogiqV3()
    events =  api.metrics.topic_metric_events(league_id=LEAGUE_ID,
                                              season_id=SEASON_ID,
                                              season_stage=SEASON_STAGE,
                                              collection_type=COLLECTION_TYPE,
                                              collection_scope=COLLECTION_SCOPE,
                                              topic_id=TOPIC_ID,
                                              metric=METRIC,

                                              )
    #save json to file
    json.dump(events, open("aaa.json","w"), indent=4)

def test_2():
    GAME_ID = "54559"
    METRIC = "Pass to Slot Success Rate"
    SCOPE = "skater"
    AGGREGATION = "total"
    LEAGUE_ID = '13'
    SEASON_ID = '12'
    SEASON_STAGE = 'regular'
    COLLECTION_TYPE = "advancedStats"
    COLLECTION_SCOPE = "team"
    TOPIC_ID = '16'
    #METRIC = 'Total Shot From Slot Attempts'
    METRIC = 'Total Shots From Inner Slot On Net Against'
    api = SportlogiqV3()
    events =  api.metrics.topic_metrics(league_id=LEAGUE_ID,
                                              season_id=SEASON_ID,
                                              # season_stage=SEASON_STAGE,
                                              collection_type=COLLECTION_TYPE,
                                              collection_scope=COLLECTION_SCOPE,
                                              topic_id=TOPIC_ID,
                                              # metric=METRIC
                                              )
    print("apa")

if __name__ == "__main__":
    # Swap these two to read the flow without argparse in the way.
    # raise SystemExit(main())
    # raise SystemExit(main_no_cli())
    raise SystemExit(test())
    # raise SystemExit(test_2())
    # raise SystemExit(test_2())
