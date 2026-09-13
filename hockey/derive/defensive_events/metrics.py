#!/usr/bin/python
"""Defensive metrics.

Every metric here is credited to the DEFENDING team: for all of these events
``Event.team_id`` is the defender, not the team in possession (verified: 82/82
on controlledentryagainst). ``Event.zone`` is likewise relative to the credited
team, so opposition shots show up as ``dz`` events.

Mapping from SportLogIQ's definitions (see CLAUDE.md) to the compiled
vocabulary, established by cross-checking counts against the mirror-image
offensive events -- see the module docstring notes on each function.

Unlike most of ``derive/``, these work on BOTH vocabularies: every event name
used here (controlledentryagainst, dumpinagainst, pressure, block, check,
receptionprevention) is present in ``playsequence.json`` as well as the
compiled file, and ``get_full_data`` returns byte-identical counts from either
source. So this module is not tied to playsequence_compiled.
"""
from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


# --- "Against" events -----------------------------------------------------

def controlled_entries_against(game: Game) -> Iterable[Event]:
    """Controlled entries conceded, one per SUCCESSFUL opposition entry.

    Verified on two games, all four team-pairs: the count of
    ``controlledentryagainst`` for a team equals the opponent's count of
    ``controlledentry`` with outcome 'successful' exactly (48/48, 34/34,
    36/36, 31/31). Denied attempts do not produce an event here -- they are
    not entries.
    """
    return [e for e in game.events if e.name == 'controlledentryagainst']


def dumpins_against(game: Game) -> Iterable[Event]:
    """Dump-ins conceded, crediting the closest defender in the lane.

    Fewer than the opponent's dump-ins (26 vs 36, 32 vs 38, 18 vs 23, 21 vs
    26 across the two sample games) because the definition requires a defender
    *in the lane* -- dump-ins with nobody in the lane are not credited.
    Outcome is 'undetermined' on every one of these, so there is no
    successful/failed split to make.
    """
    return [e for e in game.events if e.name == 'dumpinagainst']


def entry_denials(game: Game) -> Iterable[Event]:
    """DZ entry denials -- entries against where the defender came out on top.

    ``controlledentryagainst`` fires only on successful opposition entries, so
    its outcome cannot be describing whether the entry worked (it would be
    uniformly 'successful'). It is the DEFENDER's result: 'successful' means
    the opposition lost possession before entering or on the first play after
    the entry, which is exactly SportLogIQ's denial definition.

    Dump-ins against carry outcome 'undetermined' throughout and so contribute
    no denials.
    """
    return [e for e in controlled_entries_against(game) if e.outcome == 'successful']


# Entries against carry the DZ player differential in ``type``, spelled
# "<attackers>on<defenders>" -- 3on3, 2on1, 1on0. Observed across 40 games:
# 3on3, 1on2, 2on2, 2on3, 1on1, 3on2, 2on1, 1on0, 3on1.
_DIFFERENTIAL_RE = re.compile(r"^(\d+)on(\d+)$")


def player_differential(event: Event) -> tuple[int, int] | None:
    """(attackers, defenders) in the DZ at the entry, or None if not tagged.

    None means the supplier did not classify the rush, not 0on0 -- callers
    must not fold it into any bucket.
    """
    match = _DIFFERENTIAL_RE.match(event.type or "")
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def failed_entries_against(game: Game) -> Iterable[Event]:
    """Entries against the defender did NOT deny -- the complement of
    :func:`entry_denials` within :func:`controlled_entries_against`."""
    return [e for e in controlled_entries_against(game) if e.outcome == 'failed']


def _failed_by_differential(game: Game, predicate) -> list[Event]:
    out = []
    for e in failed_entries_against(game):
        diff = player_differential(e)
        if diff is not None and predicate(*diff):
            out.append(e)
    return out


def even_entries_against(game: Game) -> Iterable[Event]:
    """Failed entries against with the defence not outnumbered (m >= n)."""
    return _failed_by_differential(game, lambda n, m: m >= n)


def odd_man_entries_against(game: Game) -> Iterable[Event]:
    """Failed entries against with the attack outnumbering the defence (n > m).

    Breakaways satisfy this too (1 > 0), so :func:`breakaway_entries_against`
    is a SUBSET of this, not a sibling bucket. Subtract it if you need three
    mutually exclusive categories.
    """
    return _failed_by_differential(game, lambda n, m: n > m)


def breakaway_entries_against(game: Game) -> Iterable[Event]:
    """Failed entries against on a clean breakaway (1on0)."""
    return _failed_by_differential(game, lambda n, m: n == 1 and m == 0)


def shot_pressure(game: Game) -> Iterable[Event]:
    """One record per opposition shot, crediting the closest defender.

    ``pressure`` events match the opponent's shot count exactly (67/67, 47/47,
    60/60, 34/34), are always type 'shot', and carry the defender's location in
    ``x_adj_coord``/``y_adj_coord``. They are the location record the
    definition describes, NOT a filtered set of pressured shots -- for that
    see :func:`pressured_shots_against`.
    """
    return [e for e in game.events if e.name == 'pressure']


def pressured_shots_against(game: Game) -> Iterable[Event]:
    """Opposition shots that actually met the pressure distance criterion.

    The 8-foot/3-foot test is not recomputed here -- the supplier already
    applies it and marks the shot with the 'withpressure' flag. These are
    shot events, so they belong to the SHOOTING team; use
    :func:`shot_pressure` when you want events credited to the defender.
    """
    return [e for e in game.events if e.name == 'shot' and 'withpressure' in e.flags]


# --- Blocks ---------------------------------------------------------------

def blocked_passes(game: Game) -> Iterable[Event]:
    """Opposition pass attempts stopped by a stick or body."""
    return [e for e in game.events
            if e.name == 'block' and e.type == 'pass' and e.outcome == 'successful']


def failed_blocked_passes(game: Game) -> Iterable[Event]:
    """Pass touched on the way to the receiver but still completed."""
    return [e for e in game.events
            if e.name == 'block' and e.type == 'pass' and e.outcome == 'failed']


def blocked_shots(game: Game) -> Iterable[Event]:
    """Opposition shot attempts stopped before reaching the net."""
    return [e for e in game.events
            if e.name == 'block' and e.type == 'shot' and e.outcome == 'successful']


def failed_blocked_shots(game: Game) -> Iterable[Event]:
    """Shot touched on the way but still reaching the net."""
    return [e for e in game.events
            if e.name == 'block' and e.type == 'shot' and e.outcome == 'failed']


def blueline_holds(game: Game) -> Iterable[Event]:
    """Blocked dump-out / NZ pass that keeps the puck in the OZ.

    Type 'blueline' on a block event. Every one observed is in the OZ and
    successful, which matches the definition ("keeping the puck in the OZ") --
    note this is the one metric here credited to the ATTACKING team's player
    holding the line, so its zone is 'oz' rather than 'dz'.
    """
    return [e for e in game.events if e.name == 'block' and e.type == 'blueline']


def reception_preventions(game: Game) -> Iterable[Event]:
    """Pass prevented by making contact with the intended receiver."""
    return [e for e in game.events if e.name == 'receptionprevention']


# --- Checks ---------------------------------------------------------------

def body_checks(game: Game) -> Iterable[Event]:
    """Body checks that removed possession (the only kind SL counts)."""
    return [e for e in game.events if e.name == 'check' and e.type == 'body']


def stick_checks(game: Game) -> Iterable[Event]:
    """Stick checks separating the puck from an opponent."""
    return [e for e in game.events if e.name == 'check' and e.type == 'stick']


# --- Helpers --------------------------------------------------------------

def _for_team(events: Iterable[Event], team_id: int) -> Iterable[Event]:
    return [e for e in events if e.team_id == int(team_id)]


def _conceded_by(events: Iterable[Event], team_id: int) -> Iterable[Event]:
    """Events belonging to the OTHER team -- for metrics carried on the
    opposition's own event (a shot), credited to the team defending it."""
    return [e for e in events if e.team_id is not None and e.team_id != int(team_id)]








def get_full_data(game: Game) -> dict:
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {team_ids[0]: {}, team_ids[1]: {}}

    # Everything here is already credited to the defender except
    # pressured_shots_against, which rides on the opposition's shot event.
    conceded = {'Pressured Shots Against'}
    metrics = {
        'Controlled Entries Against': controlled_entries_against(game),
        'Dump-Ins Against': dumpins_against(game),
        'Entry Denials': entry_denials(game),
        'Entries Against Not Denied': failed_entries_against(game),
        '  ... even (m>=n)': even_entries_against(game),
        '  ... odd-man (n>m)': odd_man_entries_against(game),
        '  ... breakaway (1on0, subset of odd-man)': breakaway_entries_against(game),
        'Shot Pressure': shot_pressure(game),
        'Pressured Shots Against': pressured_shots_against(game),
        'Blocked Passes': blocked_passes(game),
        'Failed Blocked Passes': failed_blocked_passes(game),
        'Blocked Shots': blocked_shots(game),
        'Failed Blocked Shots': failed_blocked_shots(game),
        'Blueline Holds': blueline_holds(game),
        'Reception Preventions': reception_preventions(game),
        'Body Checks': body_checks(game),
        'Stick Checks': stick_checks(game),
    }

    for team_id in team_ids:
        res[team_id] = {
            label: (_conceded_by(events, team_id) if label in conceded
                    else _for_team(events, team_id))
            for label, events in metrics.items()
        }
    return res


def print_res(res):
    for k in list(res.keys()):
        print(f"\nDEFENSIVE STATS FOR {k}")
        for key in list(res[k].keys()):
            print(key, ' ', len(res[k][key]))


if __name__ == "__main__":
    GAME_ID = 191848
    GAME_ID = 186461
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir,
                  playsequence_source="playsequence_compiled")
    game = build_game(raw)

    res = get_full_data(game)
    print_res(res)
