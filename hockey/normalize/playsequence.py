from __future__ import annotations

from typing import Callable, Optional

from hockey.model.events import Event
from hockey.normalize.team_resolution import TeamResolver
from hockey.derive.current_shift import current_shift_toi


def _maybe_int(x) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None

def _maybe_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def _maybe_str(x) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s or None


def _int_list(xs):
    if not xs:
        return []
    out = []
    for x in xs:
        v = _maybe_int(x)
        if v is not None:
            out.append(v)
    return out


def _resolve_team_id(e: dict, key_name: str, key_id: str, teams: TeamResolver) -> Optional[int]:
    """
    Resolve a team ID from an event dict, handling both playsequence formats.
    Regular format: key_name holds a display name resolved via TeamResolver.
    Compiled format: key_id holds a numeric string used directly (or key_name is absent).
    """
    # If key_name and key_id differ, regular format supplies the display name under key_name.
    if key_name != key_id:
        name_val = e.get(key_name)
        if name_val is not None:
            return teams.team_id_from_string(name_val)
        id_val = e.get(key_id)
        return _maybe_int(id_val)
    # Same key (team_in_possession): try numeric parse first; fall back to display-name resolver.
    val = e.get(key_name)
    if val is None:
        return None
    as_int = _maybe_int(val)
    if as_int is not None:
        return as_int
    return teams.team_id_from_string(val)


def normalize_playsequence(
    *,
    game_id: int,
    raw_playsequence: dict,
    teams: TeamResolver,
    on_ice_lookup: Optional[Callable[[dict], dict]] = None,
) -> list[Event]:
    """Normalize playsequence events into the domain model.

    ``on_ice_lookup`` supplies the fields the compiled file drops -- the on-ice
    rosters, play_section and the expected-goals metrics. Pass
    ``RawGame.linked_fields_for``; leave it None to skip the join, in which case
    those fields stay empty. Whatever the lookup returns is also merged into the
    event's raw payload, so ``Game.events_supplier_df()`` and the DB ingest see
    one flat event dict rather than two half-populated ones.
    """
    events = []
    for e in raw_playsequence.get("events", []):
        t = float(e["game_time"])
        type = str(e.get("type", "")).strip()
        name = str(e.get("name", "")).strip()
        # regular format uses "team_in_possession" (display name); compiled uses same key but with numeric ID
        team_in_possession_id = _resolve_team_id(e, "team_in_possession", "team_in_possession", teams)
        # regular format uses "team" (display name); compiled uses "team_id" (numeric)
        team_id = _resolve_team_id(e, "team", "team_id", teams)
        # regular format uses "player_reference_id"; compiled uses "player_id"
        player_id = _maybe_int(e.get("player_reference_id") or e.get("player_id"))
        # The full playsequence carries the on-ice rosters and the expected-goals
        # metrics inline; the compiled one doesn't, so fall back to the lookup
        # that links the two files and fold the result into the payload.
        if on_ice_lookup is not None and e.get("team_forwards_on_ice_refs") is None:
            e = {**e, **(on_ice_lookup(e) or {})}
        grade = _maybe_str(e.get("expected_goals_all_shots_grade"))
        team_defencemen_on_ice_refs = _int_list(e.get("team_defencemen_on_ice_refs"))
        event_id = _maybe_int(e.get("event_id"))
        base_event_id = _maybe_int(e.get("base_event_id"))

        events.append(
            Event(
                game_id=game_id,
                t=t,
                name=name,
                type=type,
                team_id_in_possession=team_in_possession_id,
                team_id=team_id,
                player_id=player_id,
                team_defencemen_on_ice_refs=team_defencemen_on_ice_refs,
                grade=grade,
                raw=e,
                event_id=event_id,
                base_event_id=base_event_id,
                team_forwards_on_ice_refs=_int_list(
                    e.get("team_forwards_on_ice_refs")),
                team_goalie_on_ice_ref=_maybe_int(
                    e.get("team_goalie_on_ice_ref")),
                opposing_team_forwards_on_ice_refs=_int_list(
                    e.get("opposing_team_forwards_on_ice_refs")),
                opposing_team_defencemen_on_ice_refs=_int_list(
                    e.get("opposing_team_defencemen_on_ice_refs")),
                opposing_team_goalie_on_ice_ref=_maybe_int(
                    e.get("opposing_team_goalie_on_ice_ref")),
                play_section=_maybe_str(e.get("play_section")),
                expected_goals_all_shots=_maybe_float(
                    e.get("expected_goals_all_shots")),
                expected_goals_on_net=_maybe_float(
                    e.get("expected_goals_on_net")),
                expected_goals_on_net_grade=_maybe_str(
                    e.get("expected_goals_on_net_grade")),
            )
        )

    return events