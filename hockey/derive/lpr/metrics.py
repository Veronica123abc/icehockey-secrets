"""Loose puck recovery metrics. Six groups: outcome, zone and four tags.

An ``lpr`` event is a loose puck recovery -- a player taking possession of a
puck that belonged to neither team. It is the most common event this tree
covers after the pass: 1391 of them in three games.

WHICH FIELD EACH GROUP READS. The supplier is not consistent about where a
property lives, and ``hockey/derive/CLAUDE.md`` makes recording it a rule:

* Outcome      -- ``event.outcome``, 'successful' or 'failed'
* Zone         -- ``event.zone``, 'dz' / 'nz' / 'oz'
* Contested    -- 'contested' as a substring of ``event.type``
* Along Boards -- 'alongboards' in ``event.flags``
* Rebound      -- 'rebound' as a substring of ``event.type``
* Faceoff      -- 'faceoff' as a substring of ``event.type``

Along Boards is the one taken from the flags; the other three tags are inside
the type string. The type is a prefix (none / error / faceoff / rebound) with
'contested' optionally appended -- 'faceoffcontested', 'reboundcontested' --
which is why every type tag is a substring test rather than an equality.

FACEOFF IS WHAT THE SUPPLIER'S "SUCCESSFUL OZ LPRs" LEAVES OUT. Their
published per-player count is ``Successful`` + ``OZ`` + ``Is Not Faceoff``:
removing the faceoff recoveries reproduces it exactly for nine SHL 2026/27
forwards (13, 7, 51, 83, 46, 49, 66, 43 and 85 recoveries), where keeping
them overcounts by up to 30 (player 1625: 115). A recovery straight off a draw
is the faceoff's business, not the recoverer's.

ALL SIX GROUPS ARE EXHAUSTIVE, AND NONE NEEDS A COMPLEMENT ITEM. Verified
over games 186451 + 186461 + 191848, 1391 recoveries: every group covers
1391 of 1391. Outcome 1038 successful / 353 failed; Zone 627 DZ / 193 NZ /
571 OZ; Contested 472 / 919; Along Boards 938 / 453; Rebound 79 / 1312.
Faceoff was added later and checked on the same three games from
playsequence_compiled.json, which carries 2049 recoveries rather than 1391:
every group covers 2049 of 2049, Faceoff 153 / 1896.

The four tag groups are exhaustive by construction -- each is a predicate
and its negation -- so it is Outcome and Zone that are worth re-checking on
new data. ``faceoffs`` is the cautionary case: there the uncompiled
vocabulary carries a third event per draw with no outcome at all, and its
Result group needs an explicit 'Untagged' item to stay exhaustive. Nothing
like that has turned up here, but an untagged outcome or a missing zone would
drop silently out of every lane except ``LPRs · All``.
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


def is_faceoff(event: Event) -> bool:
    return 'faceoff' in event.type


def is_not_faceoff(event: Event) -> bool:
    return not is_faceoff(event)

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
    },

    'Faceoff': {
        'Is Faceoff': is_faceoff,
        'Is Not Faceoff': is_not_faceoff,
    },
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

