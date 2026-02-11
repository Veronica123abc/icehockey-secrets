from game import Game
import dotenv
import os
import numpy as np
from utils.data_tools import scoring_chances, get_team_id, add_team_id_to_playerTOI
import visualizations

dotenv.load_dotenv()
DATA_ROOT = os.getenv("DATA_ROOT")


def toi_status(game: Game):
    game_data = add_team_id_to_playerTOI(game_data)
    playsequence = game_data['playsequence']
    game_info = game_data['game-info']
    #shifts = game_data['shifts']
    shifts = game_data['playerTOI']['events']
    roster = game_data['roster']
    roster = get_roster_from_dict(roster)

    game_end_time = int(np.ceil(playsequence['events'][-1]['game_time']))

    goalies = [p for p in roster.keys() if roster[p]['position'] == "G"]
    # shift_data = [s for s in shifts if s['player_id'] not in goalies]
    shift_data = [s for s in shifts if s['player_reference_id'] not in goalies]
    home_team_id = game_info['home_team']['id']
    away_team_id = game_info['away_team']['id']
    data_home_team = process_shifts_playerTOI(game_data,team_id=home_team_id)
    data_away_team = process_shifts_playerTOI(game_data, team_id=away_team_id)
    data_home_team = shifts_reset_on_whistle(data_home_team, playsequence)
    data_away_team = shifts_reset_on_whistle(data_away_team, playsequence)
    toi_home_team = [current_shift_time_on_ice(data_home_team, p) for p in range(0,game_end_time)]
    toi_away_team = [current_shift_time_on_ice(data_away_team, p) for p in range(0, game_end_time)]
    for t in toi_home_team:
        t['mean'] = np.mean([t[k] for k in t.keys()])
    for t in toi_away_team:
        t['mean'] = np.mean([t[k] for k in t.keys()])
    return toi_home_team, toi_away_team