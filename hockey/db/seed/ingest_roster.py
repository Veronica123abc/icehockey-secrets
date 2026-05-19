import json
from hockey.db import database
from hockey.config.settings import Settings
from pathlib import Path
import numpy as np
from hockey.model.game import Game
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import  build_game

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
__all__ = [
    'settings',
]


def ingest_roster(game: Game):
    #db = database.open_database()
    db = database.open_database_azure()
    cursor = db.cursor()



    df = game.events_supplier_df()
    df = df.replace(['', 'none', 'None', 'NONE'], np.nan)



if __name__ == "__main__":
    games = json.load(open(settings.data_root_dir / 'leagues' / '213' / '20242025' / 'games.json'))
    game_ids = [g['id'] for g in games['games']]
    for game in [170659]: #tqmd(game)_ids: #[:1]:
        raw = RawGame(game_id=game, root_dir=settings.data_root_dir)
        game = build_game(raw)
        roster = game.roster
        print("df")
