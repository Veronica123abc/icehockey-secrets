#!/usr/bin/python
from __future__ import annotations

from pathlib import Path

from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def download_missing_games(
    league_id: int,
    season: str,
    catalog: DataCatalog,
    conn: SportlogiqApi | None = None,
    verbose: bool = True,
    check_filesize: bool = False,
) -> list[int]:
    """Download finished games for a season that are not fully present locally."""
    missing = catalog.missing_game_ids(league_id, season, event_status="over", check_filesize=check_filesize)
    if not missing:
        print(f"No missing completed games for league {league_id} season {season}.")
        return []
    print(f"Downloading {len(missing)} missing games for league {league_id} season {season}.")
    download_complete_games(game_ids=missing, root_dir=catalog._root, verbose=verbose)
    return missing


if __name__ == "__main__":
    LEAGUE_ID = 39
    SEASON = "20252026"

    catalog = DataCatalog(settings.data_root_dir)
    download_missing_games(LEAGUE_ID, SEASON, catalog, check_filesize=True)
