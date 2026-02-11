import collections
import os
import numpy as np
import cv2
import json
import pandas as pd
from ingest import get_map
import apiv2
from tqdm import tqdm
from collections import defaultdict

DATA_ROOT = os.getenv("DATA_ROOT")
class Game(object):
    def __init__(self, game_id: int):
        self.game_id = game_id
        self.game_data = {}
        self.compiled_data = {}

    def load_game_data(self, ignore: list = []):
        game_path = os.path.join(DATA_ROOT, str(self.game_id))
        files = [file for file in os.listdir(game_path) if file.endswith(".json") and file.replace(".json", "") not in ignore]
        for file in files:
            item = file.replace(".json", "")
            file = os.path.join(game_path, file)
            try:
                with open(file, "r") as f:
                    self.game_data[item] = json.load(f)
            except:
                print(f"Error loading {file}")

    def scoring_chances(self):
        game_info = self.game_data['game-info']
        playsequence = self.game_data['playsequence']

        home_team_name = f"{game_info['home_team']['location']} {game_info['home_team']['name']}"
        away_team_name = f"{game_info['away_team']['location']} {game_info['away_team']['name']}"

        a_chances_home_team = [(p['game_time'], 'A') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'A' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == home_team_name]
        a_chances_away_team = [(p['game_time'], 'A') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'A' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == away_team_name]
        b_chances_home_team = [(p['game_time'], 'B') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'B' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == home_team_name]
        b_chances_away_team = [(p['game_time'], 'B') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'B' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == away_team_name]
        c_chances_home_team = [(p['game_time'], 'C') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'C' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == home_team_name]
        c_chances_away_team = [(p['game_time'], 'C') for p in playsequence['events'] if
                               p['expected_goals_all_shots_grade'] == 'C' and
                               p['team_skaters_on_ice'] == 5 and
                               p['opposing_team_skaters_on_ice'] == 5 and
                               p['team_in_possession'] == away_team_name]

        self.compiled_data['scoring_chances'] = {'home_team': a_chances_home_team + b_chances_home_team + c_chances_home_team,
                                                'away_team': a_chances_away_team + b_chances_away_team + c_chances_away_team}



    def process_shifts(self, team_id=None): # , league = 'SHL', include_goalies=False, team_id=None):
            data = self.game_data["playerTOI"]['events']
            if team_id:
                data = [d for d in data if d['team_id'] == str(team_id)]
            active_shifts = {}  # Tracks ongoing shifts (IN without OUT)

            shifts = defaultdict(list)
            for event in data:
                player_id = event["player_reference_id"]
                event_time = round(float(event["game_time"]), 3)

                if event["in_or_out"] == "IN":
                    active_shifts[player_id] = event_time  # Store IN event

                elif event["in_or_out"] == "OUT":
                    if player_id in active_shifts:
                        shifts[player_id].append((active_shifts[player_id], event_time))  # Save shift
                        del active_shifts[player_id]  # Remove from active shifts

            # Add still active shifts (players who never had an OUT event)
            for player_id, in_time in active_shifts.items():
                shifts[player_id].append((in_time, None))

            self.compiled_data["shifts"] = shifts

def test():
    a = Game(41242)
    a.load_game_data()
    a.process_shifts()
    a.scoring_chances()
    print(a.game_data.keys())





if __name__ == "__main__":
    test()




