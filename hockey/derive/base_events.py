#!/usr/bin/python
"""Linking child events back to the base event they hang off.

Compiled playsequence splits many actions into a base event (the puck event
itself -- pass, shot, dumpin) and one or more derived child events
(possession, zoneexit, controlledentry, ...). A child carries a composite
``event_id`` of the form "<child>-<base>", and its ``base_event_id`` is the
base half. A base event is self-referential: its ``base_event_id`` equals its
own ``event_id``.

Only the compiled vocabulary and the ``compiled_event`` table carry these ids.
``playsequence.json`` has no per-event identifier at all, so anything built on
this module is compiled/DB-only -- which is no loss, since the derived event
types it links do not exist in the uncompiled vocabulary either.

The index is keyed by the *raw* event_id string, not ``Event.event_id``: the
typed field runs through ``_maybe_int`` and is therefore ``None`` for every
child event, which is exactly the set we need to resolve.
"""
from __future__ import annotations

from collections.abc import Iterable

from hockey.model.events import Event


def index_by_event_id(events: Iterable[Event]) -> dict[str, Event]:
    """Index events by their raw event_id. Build once per game, then reuse."""
    return {str(e.get_raw("event_id")): e for e in events}


def base_event(event: Event, index: dict[str, Event]) -> Event | None:
    """The base event ``event`` hangs off, or None if it cannot be resolved.

    Returns ``event`` itself for a base event, since those are
    self-referential. None means the link is genuinely absent (no
    base_event_id, or an id pointing outside this game's events) -- callers
    that require a base should treat it as "unknown", not as a failure.
    """
    if event.base_event_id is None:
        return None
    return index.get(str(event.base_event_id))
