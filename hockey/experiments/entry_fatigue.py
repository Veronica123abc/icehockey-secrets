from __future__ import annotations
import pathlib
import os
from pathlib import Path
from itertools import chain
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from dataclasses import dataclass, field
from hockey.model.game import Game
from dataclasses import dataclass, field
from hockey.model.game import Game
from hockey.derive.entries import zone_entries
from hockey.catalog import DataCatalog
from hockey.config.settings import Settings
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
if __name__ == "__main__":
    league_id = 13
    season = '20252026'
    stage = 'regular'
    catalog = DataCatalog(settings.data_root_dir)
    games = catalog.scheduled_game_ids(int(league_id), season, stages=[stage])


    GAME_ID = 54559
    total_sum = 0
    total = 0
    for GAME_ID in games:
        #GAME_ID = 54559
        game = None
        root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
        raw = RawGame(game_id=GAME_ID, root_dir=root)
        game = build_game(raw)
        entries = zone_entries(game)
        ht = [k.team_shift_toi - k.opposing_team_shift_toi for k in entries[game.info.home_team.id] if k.goal > 0]
        at = [k.team_shift_toi - k.opposing_team_shift_toi for k in entries[game.info.home_team.id] if k.goal > 0]
        both_teams = ht + at
        total_sum += sum(both_teams)
        total += len(both_teams)
        print(total_sum / total)