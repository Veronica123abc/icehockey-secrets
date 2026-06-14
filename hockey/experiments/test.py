# replace ##### placeholders below with real IDs from the API (see comments in each section)
import requests
import pandas as pd


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
    test()