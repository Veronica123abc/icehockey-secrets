from __future__ import annotations

from hockey.model.game import Game


def teams_rows(game: Game) -> list[dict]:
    i = game.info
    return [
        {"sl_id": i.home_team.id, "location": i.home_team.location, "name": i.home_team.name},
        {"sl_id": i.away_team.id, "location": i.away_team.location, "name": i.away_team.name},
    ]


def game_row(game: Game) -> dict:
    i = game.info
    return {
        "game_id": i.game_id,
        "home_team_sl_id": i.home_team.id,
        "away_team_sl_id": i.away_team.id,
        "home_team_display": i.home_team.display_name,
        "away_team_display": i.away_team.display_name,
    }


def players_rows(game: Game) -> list[dict]:
    return [
        {
            "player_id": p.player_id,
            "team_id": p.team_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "position": p.position,
        }
        for p in game.roster.players.values()
    ]


def events_rows(game: Game) -> list[dict]:
    return [
        {
            "game_id": e.game_id,
            "t": e.t,
            "type": e.type,
            "team_id_in_possession": e.team_id_in_possession,
            "player_id": e.player_id,
        }
        for e in game.events
    ]


def toi_intervals_rows(game: Game) -> list[dict]:
    return [
        {
            "game_id": x.game_id,
            "team_id": x.team_id,
            "player_id": x.player_id,
            "start_t": x.start_t,
            "end_t": x.end_t,
        }
        for x in game.toi
    ]