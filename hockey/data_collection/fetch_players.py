#!/usr/bin/python
from __future__ import annotations

from pathlib import Path

from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def download_players(
    catalog: DataCatalog,
    conn: SportlogiqApi | None = None,
    leagues_filter: list[int] | None = None,
    season_filter: list[str] | None = None,
) -> None:
    if conn is None:
        conn = SportlogiqApi()
    league_ids = catalog.known_league_ids()
    if leagues_filter:
        league_ids = [l for l in league_ids if l in leagues_filter]
    for league_id in league_ids:
        comp = catalog.raw_competition(league_id)
        comp.load()
        seasons = [s["name"] for s in comp.info.get("seasons", [])]
        if season_filter:
            seasons = [s for s in seasons if s in season_filter]
        for season in seasons:
            print(f"Downloading players: league={league_id} season={season}")
            try:
                data = conn.req.get(
                    conn.apiurl + f"/v1/hockey/players?season={season}&competition_id={league_id}"
                ).json()
                catalog.save_season_players(league_id, season, data)
            except Exception as e:
                print(f"Failed: league={league_id} season={season}: {e}")


if __name__ == "__main__":
    catalog = DataCatalog(settings.data_root_dir)
    download_players(catalog, leagues_filter=[213], season_filter=["20242025"])
