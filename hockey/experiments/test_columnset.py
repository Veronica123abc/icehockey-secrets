import hockey.predict.skillset as skillset
from hockey.db.game_query import query_game_ids
from hockey.db.roster_query import query_rosters
from hockey.helpers.get_roster import get_roster
from hockey.metrics.on_ice import open_connection
from pathlib import Path
from hockey.metrics.cube import Cube
from hockey.metrics.on_ice import ColumnSet

TEAM = 323
SEASON = 20262027
CUBE_DIR = Path(__file__).resolve().parents[2] / "output" / "cubes" / "league13_2627"
SKILLSET_DIR = Path(__file__).resolve().parents[1] / "config" / "skillsets"
COLUMNSET_DIR = Path(__file__).resolve().parents[1] / "config" / "columnsets"




def from_cube():
    c = ColumnSet.load(COLUMNSET_DIR / "shooting_player_woi.json")

    rows  = c.player_rows(CUBE_DIR, min_toi=50)
    #rows = s.team_rows(CUBE_DIR, min_toi=50)

    print(rows)






if __name__ == "__main__":

    from_cube()
