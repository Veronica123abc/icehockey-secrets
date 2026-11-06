import hockey.predict.skillset as skillset
from hockey.db.game_query import query_game_ids
from hockey.db.roster_query import query_rosters
from hockey.helpers.get_roster import get_roster
from hockey.metrics.on_ice import open_connection
from pathlib import Path
from hockey.metrics.cube import Cube

TEAM = 323
SEASON = 20262027
CUBE_DIR = Path(__file__).resolve().parents[2] / "output" / "cubes" / "league13_2627"
SKILLSET_DIR = Path(__file__).resolve().parents[1] / "config" / "skillsets"
COLUMNSET_DIR = Path(__file__).resolve().parents[1] / "config" / "columnsets"



def test_cube():
    cube = Cube.load(CUBE_DIR)
    print("apa")
    #rows = s.team_rows(CUBE_DIR, min_toi=50)

def from_cube():
    cube = Cube.load(CUBE_DIR)
    s = skillset.read_skillset(SKILLSET_DIR / "offensive_wo_goals")
    rows, missing = s.player_rows(CUBE_DIR, min_toi=50)
    #rows = s.team_rows(CUBE_DIR, min_toi=50)

    skillset._print_scores(s, rows) #[:10])


def from_database():
    league = 13
    season = 20262027
    team = 323

    s = skillset.read_skillset("my_skillset")
    conn = open_connection()
    players = [p.player_id for p in get_roster(team, season, conn)]
    rows, missing = skillset.load_skillset(conn, players, league, season, s)
    skillset._print_scores(s, rows[:10])


def league_from_database():
    league = 13
    season = 20262027

    s = skillset.read_skillset("my_skillset")
    conn = open_connection()
    games = query_game_ids(conn, league_sl_id=league, season=str(season))
    players = sorted({p for roster in query_rosters(conn, game_sl_ids=games).values()
                      for p in roster.players})
    rows, missing = skillset.load_skillset(conn, players, league, season, s)
    skillset._print_scores(s, rows[:10])


if __name__ == "__main__":
    #test_cube()
    from_cube()
    #from_database()
