# replace ##### placeholders below with real IDs from the API (see comments in each section)
import sys

import requests
from hockey.db import event_query
from hockey.derive import metric_catalog as catalog
from hockey.derive import context_filter as ctx

from hockey.metrics.on_ice import (AGAINST, BOTH, CREDITED, FOR, Column,
                                   ColumnSet, EVEN_STRENGTH, PlayerRow,
                                   REGULAR, WEIGHTS, lane_counts,
                                   open_connection, player_rows, team_labels)

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


ENTRIES = "Controlled entries"
RECOVERIES = "Dump-in recoveries"

COLUMNS = ColumnSet((
    Column("Entries", f"{ENTRIES} · Successful", FOR),
    Column("w/ play", (f"{ENTRIES} · Successful",
                       f"{ENTRIES} · With Play After"), FOR),
    Column("w/ shot", (f"{ENTRIES} · Successful",
                       f"{ENTRIES} · With Shot On Net",
                       f"{ENTRIES} · With Slot Shot"), FOR),
    Column("Dump-ins", "Dump-ins · Successful", FOR),
    Column("Recoveries", (f"{RECOVERIES} · Successful",
                          f"{RECOVERIES} · Offensive"), FOR),
))

def metric_test_2():
    LEAGUE_SL_ID = 17
    SEASON = "20252026"
    PLAYER_SL_ID = 24417        # None for every player
    TEAM_SL_ID = None
    ON_ICE_PLAYER_SL_ID = 24417
    PLAYER_IDS = [24417]
    conn = open_connection()

    C2 = ColumnSet((
        Column("Entries", f"{ENTRIES} · Successful", AGAINST),
    ))
    C3 = ColumnSet((
        Column("Shooting", f"Shots · All", AGAINST),
    ))
    rows, missing = player_rows(conn,
                                PLAYER_IDS,
                                LEAGUE_SL_ID,
                                SEASON,
                                columns=C3, #COLUMNS,
                                context=ctx.DEFAULT.with_values(ctx.MANPOWER,[ctx.SH1,ctx.SH2]), #.with_values(ctx.TEAM,[1396]),
                                #context=EVEN_STRENGTH,
                                #stage=REGULAR,
                                min_toi=1.0)

    print(rows)


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
    metric_test_2()