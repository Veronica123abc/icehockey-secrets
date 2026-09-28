"""One game's events, shifts and roster, without the rest of a Game.

The seam between "where the data came from" and "what the numbers are". A
``Game`` built from JSON, a ``Game`` built from the database, or three bulk
queries grouped by game all reduce to this, so an aggregation can consume any
of them without asking.

WHY NOT JUST ``Game``. This is ``Game`` minus ``info`` and minus its methods.
It exists because the bulk database read fetches events, shifts and
affiliation and no game row -- building a ``GameInfo`` for each game would be
a fourth query for metadata nothing counts. The adapters that produce these
live in ``hockey/metrics/game_bundles.py``; this module is only the shape.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hockey.model.events import Event
from hockey.model.roster import Roster
from hockey.model.toi import ToIInterval


@dataclass(frozen=True)
class GameData:
    """One game's events, shifts and roster -- whatever produced them.

    It deliberately exposes ``events`` under that name, because the base-set
    helpers in ``hockey/derive`` read exactly that attribute and nothing else
    -- ``scoring.all_goals(data)`` works, so the population definitions stay
    in the metric modules rather than being restated by every consumer.
    """
    game_id: int
    events: Sequence[Event]
    toi: Sequence[ToIInterval]
    roster: Roster

    @classmethod
    def from_game(cls, game) -> "GameData":
        return cls(game_id=game.game_id, events=game.events,
                   toi=game.toi, roster=game.roster)
