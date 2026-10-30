#!/usr/bin/python
"""Build the cube for one gameset.

    python -m hockey.examples.create_cube

Two lines of work: open a connection, build the gameset named below. The
cube lands in output/cubes/<cube name from the gameset> and shows up in the
/explore dropdown. Change NAME to build a different gameset, or run
``python -m hockey.metrics.gameset`` to build every one that has no cube yet
and bring the others up to date with games played since.
"""
from __future__ import annotations

from hockey.metrics.gameset import build
from hockey.metrics.on_ice import open_connection

NAME = "league13_2627"


def main() -> None:
    conn = open_connection()
    try:
        directory = build(conn, NAME)
    finally:
        conn.close()
    print(f"\npick '{directory.name}' in /explore")


if __name__ == "__main__":
    main()
