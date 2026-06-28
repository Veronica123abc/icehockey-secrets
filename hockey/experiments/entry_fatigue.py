from __future__ import annotations
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from dataclasses import dataclass, field
from hockey.model.game import Game
from dataclasses import dataclass, field
from hockey.model.game import Game
from hockey.derive.entries import zone_entries

if __name__ == "__main__":
    import os
    from pathlib import Path
    GAME_ID = 54559
    game = None
    root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
    raw = RawGame(game_id=GAME_ID, root_dir=root)
    game = build_game(raw)
    entries = zone_entries(game)
    print(entries)