from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Optional

from hockey.model.roster import GOALIE, Roster

#: Half-open ``[start, end)`` stretch of ice time, in game seconds.
Span = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ToIInterval:
    game_id: int
    team_id: Optional[int]     # optional until fully resolved
    player_id: int
    start_t: float
    end_t: Optional[float]     # None if no OUT seen


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """The same ice time as ``spans``, sorted and with overlaps merged.

    Lives here, on the dataclass it is about, because callers in three layers
    need it and none of them owns it. What differs between them is POLICY --
    which intervals to include, how to close one the supplier left open,
    whether to round for JSON -- and each keeps its own: :func:`skater_spans`
    below holds it for a skater's ice time, ``shift_query.toi_seconds`` for
    the same question straight from the database, and
    ``game_canvas._on_ice_for_js`` for the spans the browser tests an event's
    time against, rounded for JSON. The arithmetic is the same arithmetic, and
    it is written once.

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


def skater_spans(toi: Sequence[ToIInterval],
                 roster: Roster) -> dict[int, list[Span]]:
    """player id -> his on-ice spans in this game, merged and sorted.

    THE one answer to "when was this player on the ice", so that a TOI
    denominator, a line combination and a who-was-on-for-this-shot divide by
    the same seconds. It is the POLICY around :func:`merge_spans` rather than
    the arithmetic: drop goalies, close an open shift, merge.

    Goalies are dropped. ``end_t`` is None when the supplier never recorded
    the player coming off; it does not happen in the games checked, but the
    model allows it, so an open shift is closed at the last time anything ends
    rather than running to infinity.

    IT LIVES HERE, in the model, rather than beside its first caller. It began
    in ``metrics/on_ice_spans.py``, next to the manpower timeline that also
    needs it -- but ``derive/lines.py`` needs the same spans to build line
    combinations, and ``metrics/`` consumes ``derive/``, so leaving it up
    there bought a second copy of the policy and nothing else. It reads a
    ``ToIInterval`` and a ``Roster`` and nothing else, which is to say it was
    always addressed to the model. The move was verified rather than assumed:
    identical spans for every player of the golden twenty.
    """
    end_of_game = max((x.end_t for x in toi if x.end_t is not None), default=0.0)
    raw: dict[int, list[Span]] = defaultdict(list)
    for interval in toi:
        player = roster.players.get(interval.player_id)
        if player is not None and player.position == GOALIE:
            continue
        end = end_of_game if interval.end_t is None else interval.end_t
        if end > interval.start_t:
            raw[interval.player_id].append((interval.start_t, end))

    return {player_id: merge_spans(spans) for player_id, spans in raw.items()}


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