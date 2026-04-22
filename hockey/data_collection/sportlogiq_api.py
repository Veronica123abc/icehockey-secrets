#!/usr/bin/python
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


class SportlogiqApi:
    BASE_URL = "https://api.sportlogiq.com"

    def __init__(self):
        username = os.getenv("SPORTLOGIQ_USERNAME")
        password = os.getenv("SPORTLOGIQ_PWD")
        self.apiurl = 'https://api.sportlogiq.com'
        if not username or not password:
            raise EnvironmentError(
                "SPORTLOGIQ_USERNAME and SPORTLOGIQ_PWD must be set in the environment."
            )
        self.req = requests.Session()
        self.req.post(self.BASE_URL + "/v1/hockey/login", json={"username": username, "password": password})

    def get_schedule(self, league_id, season, stage=None):
        if stage:
            url = f"/v1/hockey/games?competition_id={league_id}&season={season}&stage={stage}"
        else:
            url = f"/v1/hockey/games?competition_id={league_id}&season={season}"
        return self.req.get(
            self.BASE_URL + url
            #self.BASE_URL + f"/v1/hockey/games?season={season}&stage={stage}&competition_id={league_id}&include_upcoming=1"
        )

    def get_finished_games(self, league_id, season, stage):
        return self.req.get(
            self.BASE_URL + f"/v1/hockey/games?season={season}&stage={stage}&competition_id={league_id}&include_upcoming=0"
        )

    def get_game_info(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}")

    def get_roster(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}/roster")

    def get_events(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}/events/full")

    def get_compiled_events(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}/events/compiled")

    def get_shifts(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}/events/shifts")

    def get_player_toi(self, game_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/games/{game_id}/playerTOI")

    def get_leagues(self):
        return self.req.get(self.BASE_URL + "/v1/hockey/competitions")

    def get_competitions(self, league_id):
        return self.req.get(self.BASE_URL + f"/v1/hockey/competitions/{league_id}")


def _fetch_events_with_retry(conn: SportlogiqApi, game_id: int) -> dict:
    while True:
        response = conn.get_events(game_id)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 1))
            time.sleep(retry_after)
        else:
            return response.json()


def download_complete_game(
    game_id: int,
    conn: SportlogiqApi | None = None,
    root_dir: str | Path | None = None,
    game_info: bool = True,
    roster: bool = True,
    playsequence: bool = True,
    playsequence_compiled: bool = True,
    shifts: bool = True,
    player_toi: bool = True,
    update: bool = False,
    verbose: bool = False,
) -> int:
    if root_dir is None:
        root_dir = os.getenv("DATA_ROOT_DIR", "")
    filepath = Path(root_dir) / str(game_id)

    if filepath.is_dir() and not update:
        if verbose:
            print(f"Game {game_id} already exists")
        return game_id

    filepath.mkdir(parents=True, exist_ok=True)

    if conn is None:
        conn = SportlogiqApi()

    if game_info:
        if verbose:
            print(f"Fetching game info for {game_id}")
        data = conn.get_game_info(game_id)
        with open(filepath / "game-info.json", "w") as f:
            json.dump(data.json(), f, indent=4)

    if roster:
        if verbose:
            print(f"Fetching roster for {game_id}")
        data = conn.get_roster(game_id)
        with open(filepath / "roster.json", "w") as f:
            json.dump(data.json(), f, indent=4)

    if playsequence:
        if verbose:
            print(f"Fetching events for {game_id}")
        events = _fetch_events_with_retry(conn, game_id)
        with open(filepath / "playsequence.json", "w") as f:
            json.dump(events, f, indent=4)

    if playsequence_compiled:
        if verbose:
            print(f"Fetching compiled events for {game_id}")
        data = conn.get_compiled_events(game_id)
        with open(filepath / "playsequence_compiled.json", "w") as f:
            json.dump(data.json(), f, indent=4)

    if shifts:
        if verbose:
            print(f"Fetching shifts for {game_id}")
        data = conn.get_shifts(game_id)
        with open(filepath / "shifts.json", "w") as f:
            json.dump(data.json(), f, indent=4)

    if player_toi:
        if verbose:
            print(f"Fetching playerTOI for {game_id}")
        data = conn.get_player_toi(game_id)
        with open(filepath / "playerTOI.json", "w") as f:
            json.dump(data.json(), f, indent=4)

    return game_id


def prompt_and_download_game(game_id: int, root_dir: str | Path) -> bool:
    """
    Ask the user whether to download a missing game, then download if confirmed.
    Returns True if the game was downloaded, False if the user declined.
    Uses a tkinter dialog when a display is available, falls back to CLI.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        confirmed = messagebox.askyesno(
            title="Missing game data",
            message=(
                f"Game {game_id} was not found in local storage.\n\n"
                "Download it now from the Sportlogiq API?"
            ),
        )
        root.destroy()
    except Exception:
        answer = input(
            f"Game {game_id} not found in local storage. "
            "Download from Sportlogiq API? [y/N] "
        ).strip().lower()
        confirmed = answer == "y"

    if confirmed:
        download_complete_game(game_id, root_dir=root_dir, verbose=True)
        return True
    return False


def download_complete_games(
    game_index_file: str | None = None,
    game_ids: list[int] | None = None,
    root_dir: str | Path | None = None,
    update: bool = True,
    max_workers: int = 4,
    verbose: bool = True,
    game_info: bool = True,
    roster: bool = True,
    playsequence: bool = True,
    playsequence_compiled: bool = True,
    shifts: bool = True,
    player_toi: bool = True,
) -> list[int]:
    if game_index_file:
        with open(game_index_file) as f:
            j = json.load(f)
        game_ids = [g["id"] for g in j["games"]]
    elif game_ids is None:
        return []

    conn = SportlogiqApi()
    completed_games: list[int] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                download_complete_game,
                gid,
                conn,
                root_dir=root_dir,
                update=update,
                verbose=verbose,
                game_info=game_info,
                roster=roster,
                playsequence=playsequence,
                playsequence_compiled=playsequence_compiled,
                shifts=shifts,
                player_toi=player_toi,
            )
            for gid in game_ids
        ]
        for future in as_completed(futures):
            try:
                gid = future.result()
                completed_games.append(gid)
                print(f"Completed: {gid} ({len(completed_games)} of {len(game_ids)})")
            except Exception as e:
                print(f"Error: {e}")



if __name__ == "__main__":
    conn = SportlogiqApi()
    games = json.load(open('games.json'))
    download_complete_game(203911,conn=conn, verbose=True)
    games = conn.get_schedule(1,'20252026')
    print(games)