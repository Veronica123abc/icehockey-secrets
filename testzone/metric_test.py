# replace ##### placeholders below with real IDs from the API (see comments in each section)
import sys

import requests
from hockey.db import event_query
from hockey.derive import metric_catalog as catalog
from hockey.derive import context_filter as ctx

def metric_test():
    LEAGUE_SL_ID = 17
    SEASON = "20252026"
    PLAYER_SL_ID = 24417        # None for every player
    TEAM_SL_ID = None
    ON_ICE_PLAYER_SL_ID = 24417   # events while this player was on the ice
    NAMES = ["shot"]            # None for every event type
    OUTCOMES = ["Successful"]             # e.g. ["successful"]
    ZONES = None                # e.g. ["oz"]
    WITH_ON_ICE = True
    LIMIT = None

    import time
    from collections import Counter

    from hockey.db import database

    conn = database.open_database_azure()
    try:
        started = time.perf_counter()
        events = event_query.query_events(
            conn,
            league_sl_id=LEAGUE_SL_ID,
            season=SEASON,
            #player_sl_id=PLAYER_SL_ID,
            team_sl_id=TEAM_SL_ID,
            on_ice_player_sl_id=ON_ICE_PLAYER_SL_ID,
            names=NAMES,
            outcomes=OUTCOMES,
            zones=ZONES,
            with_on_ice=WITH_ON_ICE,
            limit=LIMIT,
        )
        elapsed = time.perf_counter() - started
        print(len(events))
        print(elapsed)
    except:
        print("Exception occured")
        print(sys.exc_info()[0])
        print(sys.exc_info()[1])


def test():
    req = requests.Session()
    username = 'veronica.eriksson580@gmail.com' #your email address
    password = 'B1llyfjant.1'
    apiurl = 'https://app.sportlogiq.com/api/v3'
    apiurl = 'https://app.sportlogiq.com/api/v3'

    login_payload = {'username': username, 'password': password}
    req = requests.Session()

    res = req.post(apiurl + '/user/login', json=login_payload)
    # use requests.Session() to handle cookies for you
    req = requests.Session()

    res = req.post(apiurl + '/user/login', json=login_payload)
    gameid = 202628
    league_id=1
    season_id=15
    url='https://app.sportlogiq.com/api/v3/games'
    p = req.get(url)
    print(p)
    ev = req.get(apiurl + '/playerevents', params={'gameid[]': gameid, 'mode': 'compiled'})
    print(ev.request.url)
    topic = req.get(apiurl + f'/leagues/{league_id}/seasons/{season_id}/metricsetcollections/advancedStats/team/topics')
    print(topic.json())
    print(topic.request.url)
    #topic.json()

if __name__=='__main__':
    # test()
    metric_test()