#!/usr/bin/python
from __future__ import annotations

from pathlib import Path

from sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def download_competitions(
    league_id: int,
    catalog: DataCatalog,
    conn: SportlogiqApi | None = None,
) -> None:
    if conn is None:
        conn = SportlogiqApi()
    print(f"Fetching competitions for league {league_id}")
    try:
        data = conn.get_competitions(league_id).json()
        catalog.save_competition(league_id, data)
    except Exception as e:
        print(f"Error fetching competitions for league {league_id}: {e}")


def update_all_competitions(catalog: DataCatalog) -> None:
    """Aggregate all per-league competitions.json into a single all_competitions.json."""
    all_competitions = {}
    for league_id in catalog.known_league_ids():
        try:
            comp = catalog.raw_competition(league_id)
            all_competitions[str(league_id)] = comp.info
        except Exception as e:
            print(f"Skipping league {league_id}: {e}")
    catalog.save_all_competitions(all_competitions)
    print(f"Updated all_competitions.json for {len(all_competitions)} leagues.")


if __name__ == "__main__":
    catalog = DataCatalog(settings.data_root_dir)
    conn = SportlogiqApi()
    for league_id in [1, 13, 17,39, 213]:
        download_competitions(league_id, catalog, conn)
    update_all_competitions(catalog)
