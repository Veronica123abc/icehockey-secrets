#!/usr/bin/python
from __future__ import annotations

from pathlib import Path

from hockey.data_collection.sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def create_playlist(game_id:int,
                    period:int,
                    period_time:int,
                    duration:int,
                    pad:int,
                    conn=None):
    if conn is None:
        conn = SportlogiqApi()

    game_id = str(game_id)
    playlist_dict = {
         "label": "uvw",
          "segments": [
              {
                   "label": "1st clip",
                   "game_id": game_id,
                   "period": period,
                   "period_time": period_time,
                   "duration": duration,
                   "padding": pad
              }
        ]
    }

    #res = conn.req.get(conn.apiurl + '/v1/hockey/playlists')
    #res.json()


    data = conn.req.post(
        conn.apiurl + f"/v1/hockey/playlists", json=playlist_dict
    )


def fetch_playlists(playlist_id:int,
                    filename:str,
                    conn:SportlogiqApi=None):
    if conn is None:
        conn = SportlogiqApi()
    res = conn.req.get(conn.apiurl + '/v1/hockey/playlists')
    print(res.json())

    # to extract them, use the unique playlist ID taken from above res.json()
    path=conn.apiurl + f'/v1/hockey/playlists/{playlist_id}/extract'
    res_ex = conn.req.post(path)
    download_url = [x['url'] for x in res.json() if x['status'] == 'AVAILABLE']
    res = conn.req.get(download_url[1], stream=True)
    with open(filename, 'wb') as f:
        for chunk in res.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

if __name__ == "__main__":

    GAME_ID = 202401
    PERIOD = 1
    PERIOD_TIME = 300
    DURATION = 10
    CONN = SportlogiqApi()
    PLAYLIST_ID = 123456
    FILENAME="my_playlist_clip.mp4"

    fetch_playlists(playlist_id=PLAYLIST_ID,
                    filename=FILENAME,
                    conn=CONN
                    )
    create_playlist(game_id=GAME_ID,
                    period=PERIOD,
                    period_time=PERIOD_TIME,
                    duration=DURATION,
                    conn=CONN
                    )