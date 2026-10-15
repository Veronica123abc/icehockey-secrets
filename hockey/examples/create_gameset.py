#!/usr/bin/python
"""Create a gameset: every league 13 game of the 2026/27 regular season.

    python -m hockey.examples.create_gameset

Writes one small JSON file into hockey/config/gamesets/. A gameset is just
that file -- writing it by hand in an editor is equally valid; this script
only shows which keys it takes. Build its cube with create_cube.py.

NOTE ON SIZE. No "team" key, so this gameset credits every skater on the ice
in every game of the league. That is the honest meaning of "the whole
league", and it is the expensive one: a few hundred games times forty
skaters. Add "team": <id> and "players": "team" to get one bench instead.
"""
from __future__ import annotations

import json

from hockey.metrics.gameset import GAMESET_DIR

NAME = "league13_2627"

GAMESET = {
    "name": "League 13, 2026/27 regular season",
    "note": "Every game in the league. A query, so new games join on rebuild.",
    "league": 13,
    "season": "20262027",
    "stage": "regular",
    "cube": NAME,
}


def main() -> None:
    path = GAMESET_DIR / f"{NAME}.json"
    GAMESET_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(GAMESET, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    print("now: python -m hockey.examples.create_cube")


if __name__ == "__main__":
    main()
