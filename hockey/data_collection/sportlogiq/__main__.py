"""Smoke demo for the v3 client.

Run either way::

    python -m hockey.data_collection.sportlogiq     # from the repo root
    python hockey/data_collection/sportlogiq/__main__.py

The second form (what PyCharm's gutter ▶ does) executes this file as a
top-level script, so there is no parent package for relative imports to
resolve against — hence the absolute import below plus the sys.path bootstrap.
"""

from __future__ import annotations

import sys
from pathlib import Path


if __package__ in (None, ""):
    # Run as a plain script: put the repo root on sys.path so `hockey` resolves.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hockey.data_collection.sportlogiq import QueryFilters, SportlogiqV3


def main() -> None:
    api = SportlogiqV3()
    league, season, stage = 1, 12, "regular"

    topics = api.metrics.topics(league, season, "advancedStats", "team")
    print(f"{len(topics)} topics; first few:")
    for topic in topics[:5]:
        print(f"  {topic['id']:>3}  {topic['label']}")

    filters = QueryFilters(mps=["ES"], mpsskaters=["5v5"], teamid=[322])
    values = api.metrics.topic_values(
        league, season, stage, "advancedStats", "team", "1",
        aggregationtype="sum", filters=filters,
    )
    print("\n5v5 scoring-chance totals for team 322:")
    for key, value in list(values[0].items())[1:6]:
        print(f"  {key:45} {value}")


if __name__ == "__main__":
    main()
