#!/usr/bin/python
from __future__ import annotations

from pathlib import Path

from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def download_game_index(
    league_id: int,
    season: str,
    catalog: DataCatalog,
    stage: str | None = None,
    conn: SportlogiqApi | None = None,
) -> None:
    print(f"Fetching schedule: league={league_id} season={season} stage={stage or 'all'}")
    if conn is None:
        conn = SportlogiqApi()
    url = f"/v1/hockey/games?season={season}&competition_id={league_id}&include_upcoming=1&withvidparams=true"
    if stage:
        url += f"&stage={stage}"
    data = conn.req.get(conn.apiurl + url).json()
    catalog.save_season_schedule(league_id, season, data, stage=stage)


def download_all_game_indexes_per_season(
    league_id: int,
    catalog: DataCatalog,
    conn: SportlogiqApi | None = None,
) -> None:
    if conn is None:
        conn = SportlogiqApi()
    comp = catalog.raw_competition(league_id)
    comp.load()
    for season in comp.info.get("seasons", []):
        download_game_index(league_id, season["name"], catalog, conn=conn)


def download_all_game_indexes_per_stage(
    league_id: int,
    catalog: DataCatalog,
    conn: SportlogiqApi | None = None,
) -> None:
    if conn is None:
        conn = SportlogiqApi()
    comp = catalog.raw_competition(league_id)
    comp.load()
    for season in comp.info.get("seasons", []):
        for stage in season.get("stages", []):
            download_game_index(league_id, season["name"], catalog, stage=stage["name"], conn=conn)


if __name__ == "__main__":
    LEAGUE_ID = 39

    catalog = DataCatalog(settings.data_root_dir)
    download_all_game_indexes_per_season(LEAGUE_ID, catalog)
