from __future__ import annotations
from hockey.io.raw_game import RawGame
from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.normalize.playsequence import normalize_playsequence
from hockey.normalize.player_toi import normalize_player_toi
from hockey.normalize.roster import normalize_roster
from hockey.normalize.team_resolution import TeamResolver
import time
import warnings

def _opt_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_game_info(*, game_id: int, raw_game_info: dict) -> GameInfo:
    ht = raw_game_info["home_team"]
    at = raw_game_info["away_team"]
    return GameInfo(
        game_id=game_id,
        home_team=TeamInfo(id=int(ht["id"]), location=str(ht["location"]), name=str(ht["name"])),
        away_team=TeamInfo(id=int(at["id"]), location=str(at["location"]), name=str(at["name"])),
        date=raw_game_info.get("date"),
        stage=raw_game_info.get("stage"),
        home_final_score=_opt_int(raw_game_info.get("home_final_score")),
        away_final_score=_opt_int(raw_game_info.get("away_final_score")),
    )


def build_game(raw: RawGame, *, link_on_ice: bool = True) -> Game:
    """Build a Game from the raw JSON files.

    ``link_on_ice`` fills each event's on-ice rosters, play_section and
    expected-goals metrics by linking playsequence_compiled.json back to
    playsequence.json, which is the only file carrying them. It costs one extra file read (~0.09s per game) and is
    lazy: with link_on_ice=False, playsequence.json is never opened. If that
    file is missing, the on-ice fields are left empty and a warning is raised
    rather than failing the load.
    """
    info = normalize_game_info(game_id=raw.game_id, raw_game_info=raw.game_info)
    resolver = TeamResolver.from_game_info(info)

    on_ice_lookup = None
    # playsequence.json carries the rosters inline, so linking it to itself
    # would only rebuild indexes to re-find events we already have.
    if link_on_ice and raw.playsequence_source != "playsequence":
        try:
            raw.playsequence_raw
        except FileNotFoundError:
            warnings.warn(
                f"playsequence.json missing for game {raw.game_id}; "
                "on-ice rosters and expected goals will be empty on every event.",
                RuntimeWarning,
                stacklevel=2,
            )
        else:
            on_ice_lookup = raw.linked_fields_for

    events = normalize_playsequence(
        game_id=raw.game_id,
        raw_playsequence=raw.playsequence,
        teams=resolver,
        on_ice_lookup=on_ice_lookup,
    )
    toi = normalize_player_toi(
        game_id=raw.game_id,
        raw_player_toi=raw.player_toi,
        teams=resolver,
    )
    roster = normalize_roster(game_id=raw.game_id, raw_roster=raw.roster)


    return Game(
        info=info,
        events=events,
        toi=toi,
        roster=roster,
    )

if __name__ == "__main__":
    import os
    from pathlib import Path
    from hockey.io.raw_game import RawGame


    GAME_ID = 204628
    root_dir = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
    raw_game = RawGame(GAME_ID, root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw_game)
    print(game)
