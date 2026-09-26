#!/usr/bin/env python
"""The smallest possible players.search call.

    python examples/simple_player_search.py

The endpoint needs a season (seasonid + seasonstage) AND a scope
(teamid or leagueid). Leave any of those out and it answers
400 "Params not set correctly".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hockey.data_collection.sportlogiq import SportlogiqV3

api = SportlogiqV3()

result = api.players.search(leagueid=1, seasonid=12, seasonstage="regular",withseasonsummaries=True)

for player in result["players"]:
    #print(player["id"], player["firstName"], player["lastName"])
    for k in list(player.keys()):
        print(f"{k}: {player[k]}")
