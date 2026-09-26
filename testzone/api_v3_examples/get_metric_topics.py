#!/usr/bin/env python
"""The smallest possible players.search call.

    python examples/simple_player_search.py

The endpoint needs a season (seasonid + seasonstage) AND a scope
(teamid or leagueid). Leave any of those out and it answers
400 "Params not set correctly".
"""

import sys
from pathlib import Path
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hockey.data_collection.sportlogiq import SportlogiqV3

# api = SportlogiqV3()
# a = api.metrics.topic_metrics(13, 12, "advancedStats", "skater", 3)
# # ev = api.metrics.topic_metric_events(league_id=13, season_id=12, season_stage='regular',collection_scope='skater', collection_type='advancedStats', topic_id=1, team_id=363)
# # topics = api.metrics.topics(league_id=1, season_id=12, collection_scope='skater', collection_type='advancedStats')
# # json_str = json.dumps(topics, indent=4)
# # with open("topics.json", "w") as f:
# #     f.write(json_str)
# print(a)


import json
from typing import get_args
from hockey.data_collection.sportlogiq import SportlogiqV3
from hockey.data_collection.sportlogiq.enums import CollectionType, CollectionScope

def walk_metrics(nodes):
    """Yield every non-group metric node, however deeply nested."""
    for node in nodes:
        if node["type"] == "group":
            yield from walk_metrics(node.get("metrics", ()))
        else:
            yield node


def metric_leaves(catalog, collection_key="advancedStats/team"):
    """All leaf metricKeall its topics."""
    collection = catalog["collections"][collection_key]
    return [
        metric["metricKey"]
        for topic in collection.values()
        for metric in walk_metrics(topic["detail"]["metrics"])
    ]

def metric_leaves_hack(catalog):
    collection = catalog["collections"]['advancedStats/team']
    topics = list(collection.keys())
    topic_categories = [collection[topic]['detail']['metrics'] for topic in topics]
    res=[]
    for topic_category in topic_categories:
        for topic_metric in topic_category:
            if topic_metric['type'] != 'group':
                res.append(topic_metric['metricKey'])
            else:
                for metric_0 in topic_metric['metrics']:
                    if metric_0['type'] != 'group':
                        #pass
                        res.append(metric_0['metricKey'])
                        #print(metric_0['metricKey'])
                    else:
                        #print("level2")
                        for metric_1 in metric_0['metrics']:
                            if metric_1['type'] != 'group':
                                res.append(metric_1['metricKey'])
                                #print(metric_1['metricKey'])
                            else:
                                #print("level3")
                                for metric_2 in metric_1['metrics']:
                                    if metric_2['type'] != 'group':
                                        res.append(metric_2['metricKey'])
                                        #print(metric_2['metricKey'])
                                    else:
                                        continue
    return res

# catalog = json.load(open("metric_catalog.json"))
# leaves = metric_leaves(catalog)
# print(leaves)
# exit(0)
# print(collection)

# get topics for collection

catalog = json.load(open("metric_catalog.json"))
#[catalog[k]['detail']['label'] for k in catalog.keys()]

ANY_LEAGUE, ANY_SEASON = 1, 12   # ignored by the definition endpoints

api = SportlogiqV3()
t = api.players.search(leagueid=(1,13,17), seasonid=(1,2,3,4,5,6,7,8,9,10,11,12,13), seasonstage=('regular', 'playoffs'))
#t = api.players.search()
json.dump(t, open("/home/veronica/hockeystats/ver3/players/players.json", "w"), indent=4)
exit(0)
t = api.teams.list(withreferences=True)
json.dump(t, open("/home/veronica/hockeystats/ver3/teams/teams_with_references.json", "w"), indent=4)
exit(0)
catalog = {"collections": {}, "reports": {}}

for ctype in get_args(CollectionType):
  for scope in get_args(CollectionScope):
      entry = {}
      for t in api.metrics.topics(ANY_LEAGUE, ANY_SEASON, ctype, scope):
          entry[t["id"]] = {
              "label": t["label"],
              "detail": api.metrics.topic_metrics(
                  ANY_LEAGUE, ANY_SEASON, ctype, scope, t["id"]),
          }
      catalog["collections"][f"{ctype}/{scope}"] = entry

for report in ("pregamecomplete", "playercard", "dashboard", "tradstats", "rosterstats"):
  catalog["reports"][report] = api.metrics.league_report_defs(
      ANY_LEAGUE, ANY_SEASON, report)

json.dump(catalog, open("metric_catalog.json", "w"), indent=2)
