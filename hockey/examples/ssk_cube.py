#!/usr/bin/python
"""The smallest thing that builds a cube, and three questions asked of it.

    python -m hockey.examples.ssk_cube

Södertälje SK in Hockey Allsvenskan, the season so far. No config file, no
argparse: four constants, build, save. That is the whole of it -- everything
after `cube.save(...)` is only looking at what you built, and could equally
happen next week in a notebook against `Cube.load(OUT)`.
"""
from __future__ import annotations

from pathlib import Path

from hockey.db.game_query import query_game_ids
from hockey.metrics.cube import Cube, build_cube
from hockey.metrics.on_ice import EVEN_STRENGTH, open_connection
from hockey.reports.helpers.get_roster import get_roster

LEAGUE, SEASON, TEAM = 17, "20252026", 1396       # Allsvenskan, SSK
OUT = Path("output/cubes/ssk_2526")


def build() -> Cube:
    """Count every catalog lane for every SSK game of the season. Slow once."""
    conn = open_connection()
    try:
        games = query_game_ids(conn, league_sl_id=LEAGUE, season=SEASON,
                               stage="regular", team_sl_ids=TEAM)
        # players= limits WHO is credited, not what is counted: the opponents'
        # events are still there, on the 'against' side. Omit it and all forty
        # skaters on the ice get their own rows, which is several times larger.
        cube = build_cube(conn, games, players=get_roster(TEAM, SEASON))
    finally:
        conn.close()
    cube.save(OUT)
    return cube


def main() -> None:
    cube = build() if not (OUT / "meta.json").is_file() else Cube.load(OUT)
    print(cube, "\n")

    # 1. Who played, and how much.
    print(cube.summary().head().to_string(float_format="%.1f"), "\n")

    # 2. One lane, one number: SSK's shots on net while each skater was out.
    shots = cube.wide()["Shots · On Net"].sort_values(ascending=False)
    print(shots.head().rename(index=cube.names).to_string(), "\n")

    # 3. The same thing even strength only, per 60 -- a slice, not a rebuild.
    #    min_minutes drops the 4-minute call-up whose rate is otherwise top.
    even = cube.slice_context(EVEN_STRENGTH)
    print(even.wide(per60=True, min_minutes=30)["Shots · On Net"]
          .sort_values(ascending=False).head()
          .rename(index=cube.names).to_string(float_format="%.1f"))


if __name__ == "__main__":
    main()
