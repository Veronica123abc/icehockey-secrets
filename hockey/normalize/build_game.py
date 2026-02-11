from __future__ import annotations
from hockey.io.raw_game import RawGame
from hockey.model.game import Game
from hockey.model.game_info import GameInfo, TeamInfo
from hockey.normalize.playsequence import normalize_playsequence
from hockey.normalize.player_toi import normalize_player_toi
from hockey.normalize.roster import normalize_roster
from hockey.normalize.team_resolution import TeamResolver


def normalize_game_info(*, game_id: int, raw_game_info: dict) -> GameInfo:
    ht = raw_game_info["home_team"]
    at = raw_game_info["away_team"]
    return GameInfo(
        game_id=game_id,
        home_team=TeamInfo(id=int(ht["id"]), location=str(ht["location"]), name=str(ht["name"])),
        away_team=TeamInfo(id=int(at["id"]), location=str(at["location"]), name=str(at["name"])),
    )


def build_game(raw: RawGame) -> Game:
    info = normalize_game_info(game_id=raw.game_id, raw_game_info=raw.game_info)

    resolver = TeamResolver.from_game_info(info)
    events = normalize_playsequence(
        game_id=raw.game_id,
        raw_playsequence=raw.playsequence,
        teams=resolver,
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