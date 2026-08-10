#!/usr/bin/env python
"""Fetch every player who has been on a team's roster, across all seasons.

    python examples/fetch_team_players.py
    python examples/fetch_team_players.py --teamid 322 --seasonstage playoffs
    python examples/fetch_team_players.py --seasonid 12 --out edm.csv

Why this is not a single call
-----------------------------
``GET /api/v3/players`` will not accept a team filter on its own. Verified
against the live API, it needs ``teamid`` **and** ``seasonid`` **and**
``seasonstage`` together — drop any one and it answers 400 "Params not set
correctly". ``leagueid`` may be added, but only alongside ``seasonid``; it
cannot stand in for it.

So "all players for a team" means one request per season, unioned. This script
discovers which seasons a league actually has (from the schedule) and walks
them.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hockey.data_collection.sportlogiq import SportlogiqError, SportlogiqV3


def season_ids_for_league(api: SportlogiqV3, league_id: int | str) -> list[str]:
    """Season ids that actually have games, newest first.

    There is no "list seasons" endpoint in v3, so this reads them off the
    schedule.
    """
    payload = api.games.list(leagueid=[league_id])
    games = payload.get("games") or []
    seasons = {game["seasonId"] for game in games if game.get("seasonId")}
    return sorted(seasons, key=int, reverse=True)


def fetch_players(
    api: SportlogiqV3,
    team_id: int | str,
    league_id: int | str,
    season_stage: str,
    season_ids: list[str],
    verbose: bool = True,
) -> dict[str, dict]:
    """Union of roster players across seasons, keyed by player id.

    Each player gains a ``seasons`` list recording where they showed up.
    """
    players: dict[str, dict] = {}

    for season_id in season_ids:
        try:
            found = api.players.search(
                teamid=[team_id],
                leagueid=[league_id],
                seasonid=[season_id],
                seasonstage=[season_stage],
            ).get("players") or []
        except SportlogiqError as exc:
            # A team that did not exist in a given season is a normal miss.
            if verbose:
                print(f"  season {season_id:>3}: skipped (HTTP {exc.status})")
            continue

        for player in found:
            existing = players.setdefault(player["id"], {**player, "seasons": []})
            existing["seasons"].append(season_id)

        if verbose:
            print(f"  season {season_id:>3}: {len(found):>3} players")

    return players


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--teamid", default=1, help="team id (default: 1, EDM)")
    parser.add_argument("--leagueid", default=1, help="league id (default: 1, NHL)")
    parser.add_argument(
        "--seasonstage",
        default="regular",
        choices=["training", "preseason", "regular", "playoffs"],
    )
    parser.add_argument(
        "--seasonid",
        action="append",
        help="restrict to these season ids (repeatable); default is all seasons",
    )
    parser.add_argument("--out", type=Path, help="write results to this CSV")
    args = parser.parse_args()

    api = SportlogiqV3()
    a = api.players.search(seasonstage=["regular"], seasonid=[12], leagueid=[1])
    try:
        team = api.teams.get(args.teamid)
        print(f"Team {args.teamid}: {team.get('displayName') or team.get('name')}")
    except SportlogiqError as exc:
        print(f"Could not read team {args.teamid}: {exc}", file=sys.stderr)
        return 1

    season_ids = args.seasonid or season_ids_for_league(api, args.leagueid)
    print(f"Searching {len(season_ids)} season(s), stage={args.seasonstage}:")

    players = fetch_players(
        api, args.teamid, args.leagueid, args.seasonstage, season_ids
    )

    print(f"\n{len(players)} distinct players")
    ordered = sorted(
        players.values(), key=lambda p: (p.get("lastName") or "", p.get("firstName") or "")
    )
    for player in ordered:
        seasons = ",".join(player["seasons"])
        name = f"{player.get('firstName','')} {player.get('lastName','')}".strip()
        print(f"  {player['id']:>7}  {name:<28} seasons: {seasons}")

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "firstName", "lastName", "birthdate", "seasons"])
            for player in ordered:
                writer.writerow(
                    [
                        player["id"],
                        player.get("firstName", ""),
                        player.get("lastName", ""),
                        player.get("birthdate", ""),
                        " ".join(player["seasons"]),
                    ]
                )
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
