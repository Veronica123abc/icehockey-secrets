from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class ToIInterval:
    game_id: int
    team_id: Optional[int]     # optional until fully resolved
    player_id: int
    start_t: float
    end_t: Optional[float]     # None if no OUT seen


def merge_spans(spans: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """The same ice time as ``spans``, sorted and with overlaps merged.

    Lives here, on the dataclass it is about, because three callers in three
    layers need it and none of them owns it: ``skater._skater_spans`` (a TOI
    denominator), ``shift_query.toi_seconds`` (the same, straight from the
    database) and ``game_canvas._on_ice_for_js`` (the spans the browser tests
    an event's time against). What differs between them is POLICY -- which
    intervals to include, how to close one the supplier left open, whether to
    round for JSON -- and each keeps its own. The arithmetic is the same
    arithmetic, and now it is written once.

    Merging is defensive rather than load-bearing: no player's intervals
    overlap in the games checked. But adding a double-recorded second, rather
    than counting it once, would inflate a denominator silently -- and a
    denominator that is quietly too large makes every rate over it quietly too
    small, which is the kind of wrong that does not announce itself.

    Touching spans are merged: ``(0, 10)`` and ``(10, 20)`` become ``(0, 20)``,
    which is the same total time either way, and keeps a half-open interval
    from being split at a change of shift it never left the ice for.
    """
    ordered = sorted(spans)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = out[-1]
        if start <= last_end:
            out[-1] = (last_start, max(last_end, end))
        else:
            out.append((start, end))
    return out


@dataclass(frozen=True, slots=True)
class PlayerCurrentShiftToi:
    team_id: Optional[int]
    player_id: Optional[int]
    current_toi: Optional[float ]

@dataclass(frozen=True, slots=True)
class CurrentShiftTOI:
    game_id: int
    t: float
    players: list[PlayerCurrentShiftToi]