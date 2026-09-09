#!/usr/bin/python
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
from hockey.derive.base_events import index_by_event_id, base_event

from collections.abc import Iterable

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def possessions(game: Game) -> Iterable[Event]:
    return [e for e in game.events if e.name == 'possession']


def successful_possessions(game: Game) -> Iterable[Event]:
    """Possessions SportLogIQ counts as successful.

    Both the possession event and the base event it hangs off must be
    successful -- see this folder's CLAUDE.md. Compiled vocabulary only.
    """
    index = index_by_event_id(game.events)
    out = []
    for e in possessions(game):
        if e.outcome != 'successful':
            continue
        base = base_event(e, index)
        if base is not None and base.outcome == 'successful':
            out.append(e)
    return out


def failed_possessions(game: Game) -> Iterable[Event]:
    """Every possession that is not successful by the definition above."""
    successful = set(id(e) for e in successful_possessions(game))
    return [e for e in possessions(game) if id(e) not in successful]


def _for_team(events: Iterable[Event], team_id: int) -> Iterable[Event]:
    return [e for e in events if e.team_id == int(team_id)]

def turnovers(game: Game) -> Iterable[Event]:
    return [e for e in possessions(game) if e.outcome == 'failed']

def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    all_possessions = possessions(game)
    successful = successful_possessions(game)
    # possession events whose own outcome is successful but whose base failed
    own_outcome_only = [e for e in all_possessions if e.outcome == 'successful']

    for team_id in team_ids:
        res[team_id] = {
            'Possessions': _for_team(all_possessions, team_id),
            'Successful Possessions': _for_team(successful, team_id),
            'Possession Event Successful (base ignored)': _for_team(own_outcome_only, team_id),
            'Failed Possessions': _for_team(failed_possessions(game), team_id),
            'Turnovers': _for_team(turnovers(game), team_id)
        }
    res[team_ids[0]]['Takeovers'] = res[team_ids[1]]['Turnovers']
    res[team_ids[1]]['Takeovers'] = res[team_ids[0]]['Turnovers']
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nPOSSESSION STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)
