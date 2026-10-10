"""Faceoff metrics. One group: who won the draw.

THE TWO VOCABULARIES DISAGREE ON HOW MANY EVENTS A DRAW IS, and the group has
to cover both. Verified over games 186449 + 186461 + 191848:

* ``playsequence_compiled`` -- 328 faceoffs, TWO per draw: 164 'successful'
  (the winner) and 164 'failed' (the loser). Nothing else.
* ``playsequence`` -- 492, THREE per draw: the same 164 + 164, plus 164
  carrying no outcome at all. That third one is the puck drop itself -- no
  team_id, no player_id, and a ``type`` that is the zone ('nz', 'hoz', 'hdz')
  rather than a result. All three share a timestamp.

So 'Untagged' is not decoration: without it Result would cover 328 of 492 on
the uncompiled path and the lane counts would silently disagree between
sources. With it, Result totals 328 and 492 respectively -- exhaustive on
both. The untagged events carry no team, so ``for_team`` drops them from
either side of :func:`get_full_data`; they are visible only in the whole-
population lanes.
"""
from __future__ import annotations
from collections.abc import Iterable
from hockey.model.events import Event
from hockey.derive.filter_group import FilterGroups, Predicate, for_team

from hockey.model.events import Event
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.normalize.build_game_db import build_game_from_db
from hockey.model.game import Game
from hockey.db.database import open_database_azure
from hockey.derive.filter_group import FilterGroups, Predicate, for_team


# Settings, resolved on first use rather than at import -- see
# hockey.config.settings.settings for why this must not be eager.
from hockey.config.settings import settings as _settings

def is_contested(event: Event) -> bool:
    return 'contested' in event.type

def is_not_contested(event: Event) -> bool:
    return not is_contested(event)

def is_alongboards(event: Event) -> bool:
    return 'alongboards' in event.flags

def is_not_alongboards(event: Event) -> bool:
    return not is_alongboards(event)


def is_rebound(event: Event) -> bool:
    return 'rebound' in event.type

def is_not_rebound(event: Event) -> bool:
    return not is_rebound(event)

def is_successful(event: Event) -> bool:
    return event.outcome == 'successful'

def is_failed(event: Event) -> bool:
    return event.outcome == 'failed'

def in_dz(event: Event) -> bool:
    return event.zone == 'dz'

def in_nz(event: Event) -> bool:
    return event.zone == 'nz'

def in_oz(event: Event) -> bool:
    return event.zone == 'oz'


LPR_FILTERS: dict[str, dict[str, Predicate]] = {
    'Outcome': {
        'Successful': is_successful,
        'Failed': is_failed,
    },
    'Zone': {
        'DZ': in_dz,
        'NZ': in_nz,
        'OZ': in_oz,
    },
    'Contested': {
        'Is Contested': is_contested,
        'Is Not Contested': is_not_contested,
    },

    'Along Boards': {
        'Is Alongboards': is_alongboards,
        'Is Not Alongboards': is_not_alongboards,
    },

    'Rebound': {
        'Is Rebound': is_rebound,
        'Is Not Rebound': is_not_rebound
    }
}

LPR = FilterGroups('lpr', LPR_FILTERS, 'LPRs')



# --- Base sets ------------------------------------------------------------

def all_lprs(game: Game, team_id: int | str | None = None) -> list[Event]:
    events = [e for e in game.events if e.name == 'lpr']
    return for_team(events, team_id) if team_id else events


# --- Filtering ------------------------------------------------------------

def filter_lprs(lprs: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores for spaces, e.g.::

        filter_shots(shots, Result=['On Net'], Shot_Location=['Inner Slot'])

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive.
    """
    return LPR.filter(lprs, **selections)


def check_groups_exhaustive(lprs: Iterable[Event]) -> dict[str, bool]:
    """Whether each group's items together cover every shot.

    The property the filter UI depends on: tick everything in a group and you
    get all the shots back.
    """
    return LPR.check_exhaustive(lprs)


# --- Helpers --------------------------------------------------------------

_for_team = for_team



def get_full_data(game) -> dict:
    """team id -> {lane key: events}. What ``golden.py`` sweeps."""
    lprs = [e for e in game.events if e.name == LPR.name]
    return {team: LPR.rows(for_team(lprs, team))
            for team in (game.info.home_team.id, game.info.away_team.id)}



if __name__ == "__main__":
    #season_stats(17,"20252026")
    #exit(0)
    GAME_ID = 191848
    GAME_ID = 186461
    GAME_ID = 186451
    # raw = RawGame(game_id=GAME_ID, root_dir=_settings().data_root_dir,
    #               playsequence_source="playsequence_compiled")
    # game = build_game(raw)
    conn = open_database_azure("hockey_v2_test")
    game = build_game_from_db(GAME_ID, conn)
    # res = get_full_data(game)
    # print_res(res)

    lprs = all_lprs(game)
    print(len(lprs))
    print("\nexhaustiveness:", check_groups_exhaustive(lprs))
    print("Contested lprs:",
          len(filter_lprs(lprs, Contested=['Is Contested'],
                           **{'Outcome': ['Successful']})))

