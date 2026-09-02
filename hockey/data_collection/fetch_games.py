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
    LEAGUE_ID = 17
    SEASON = "20252026"

    catalog = DataCatalog(settings.data_root_dir)
    #download_complete_games(game_ids=[203978], root_dir=catalog._root, verbose=True)
    #exit(0)
    download_missing_games(LEAGUE_ID, SEASON, catalog, check_filesize=True)
    #download_complete_games(game_ids=[203978], root_dir=catalog._root, verbose=True)

    modo_games = ['203341', '203339', '203337', '203335', '203333', '203331', '203329', '201942', '201941', '201937', '201934', '201932', '201929', '186807', '186802', '186794', '186791', '186781', '186772', '186768', '186761', '186755', '186741', '186735', '186729', '186723', '186718', '186710', '186699', '186692', '186687', '186678', '186675', '186664', '186655', '186650', '186643', '186636', '186631', '186619', '186617', '186611', '186602', '186591', '186585', '186578', '186573', '186567', '186560', '186555', '186553', '186548', '186539', '186534', '186525', '186515', '186510', '186502', '186498', '186487', '186477', '186473', '186469', '186460', '186452']