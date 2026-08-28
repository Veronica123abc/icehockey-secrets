
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from hockey.data_collection.sportlogiq import SportlogiqV3

ANY_LEAGUE, ANY_SEASON = 1, 12   # ignored by the definition endpoints
LEAGUES = (1,13,17)
ALL_SEASONS = (range(13))
ALL_STAGES = ('preseason', 'regular', 'playoffs')
api = SportlogiqV3()
a=api.metrics.topic_metric_events(13,12,"regular","advancedStats", "skater",1, metric="Shot From Slot Attempts")
json.dump(a, sys.stdout, indent=4)
exit(0)
t = api.players.search(leagueid=LEAGUES, seasonid=ALL_SEASONS, seasonstage=ALL_STAGES) #(1,2,3,4,5,6,7,8,9,10,11,12,13), seasonstage=('regular', 'playoffs'))
json.dump(t, open("/home/veronica/hockeystats/ver3/players/players.json", "w"), indent=4)
