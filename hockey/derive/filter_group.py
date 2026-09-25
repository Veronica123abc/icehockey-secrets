#!/usr/bin/python
"""Shared machinery for the ``*_FILTERS`` dictionaries in ``derive/``.

Every metric module describes one population of events with a dictionary of
GROUPS, each group mapping a display name to an ``Event -> bool`` predicate::

    SHOT_FILTERS: FilterSpec = {
        'Result': {'On Net': is_on_net, 'Blocked': is_blocked, ...},
        'Pressure': {'Pressure': is_pressured, 'No Pressure': is_not_pressured},
    }

Four operations over such a dictionary -- pick one item, apply a checkbox-style
selection, expand every group, check exhaustiveness -- are identical whatever
the population is, so they live here instead of being copied into each module.
A module binds them to its own dictionary with :class:`FilterGroups` and
re-exports thin named wrappers, so ``filter_shots`` / ``filter_passes`` and
friends keep working exactly as before.

THE CONTRACT. A group is *exhaustive*: ticking every item in it returns the
whole population back. Exhaustive does NOT mean disjoint -- several groups
carry deliberate overlap (shooting's 'Slot' is the union of inner and outer;
'Led to Goal' is a subset of 'On Net'), and where a group would otherwise leak
its module adds an explicit complement item ('Untagged', 'Untyped',
'Ungraded', 'No Pressure'). :meth:`FilterGroups.check_exhaustive` is how that
contract is verified against real games rather than assumed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from hockey.model.events import Event

#: One filter item: does this event belong in the bucket?
Predicate = Callable[[Event], bool]

#: A whole filter dictionary: group name -> item name -> predicate.
FilterSpec = dict[str, dict[str, Predicate]]


def for_team(events: Iterable[Event], team_id: int | str) -> list[Event]:
    """Events credited to one team. ``team_id`` may be an int or a str.

    "Credited to" is ``context_filter.team_of``, imported here rather than
    respelled: the same question -- whose event is this -- is asked by the
    situation filter's Team dimension and by the reports' for/against split,
    and one answer is the point. The import is one-way; context_filter knows
    nothing of this module.
    """
    from hockey.derive.context_filter import team_of
    return [e for e in events if team_of(e) == int(team_id)]


def matching(events: Iterable[Event], filters: FilterSpec,
             group: str, item: str) -> list[Event]:
    """Events passing one named filter item."""
    try:
        predicate = filters[group][item]
    except KeyError:
        raise KeyError(f"unknown filter {group!r}/{item!r}; groups are "
                       f"{sorted(filters)}") from None
    return [e for e in events if predicate(e)]


def apply_selection(events: Iterable[Event], filters: FilterSpec,
                    **selections: Iterable[str]) -> list[Event]:
    """Apply a checkbox-style selection: OR within a group, AND across groups.

    Groups are named by keyword with underscores standing in for spaces::

        apply_selection(shots, SHOT_FILTERS, Result=['On Net'],
                        Shot_Location=['Inner Slot'])

    A group whose name is not a valid identifier ('1-Timer', '2nd Chance') is
    passed by unpacking instead: ``**{'1-Timer': ['1-Timer Taken']}``.

    An unmentioned group is unconstrained, and selecting every item in a group
    is the same as not mentioning it -- that is what makes the groups
    exhaustive. A single item may be given as a bare string.
    """
    events = list(events)
    for raw_group, items in selections.items():
        group = raw_group if raw_group in filters else raw_group.replace('_', ' ')
        if group not in filters:
            raise KeyError(f"unknown filter group {group!r}; "
                           f"groups are {sorted(filters)}")
        if isinstance(items, str):
            items = [items]
        predicates = []
        for item in items:
            try:
                predicates.append(filters[group][item])
            except KeyError:
                raise KeyError(f"unknown filter {group!r}/{item!r}; items are "
                               f"{sorted(filters[group])}") from None
        events = [e for e in events if any(p(e) for p in predicates)]
    return events


def breakdown(events: Iterable[Event],
              filters: FilterSpec) -> dict[str, dict[str, list[Event]]]:
    """Every group and item, applied to the given events."""
    events = list(events)
    return {group: {item: [e for e in events if predicate(e)]
                    for item, predicate in items.items()}
            for group, items in filters.items()}


def check_exhaustive(events: Iterable[Event],
                     filters: FilterSpec) -> dict[str, bool]:
    """Whether each group's items together cover every event.

    The property the filter UI depends on: tick everything in a group and you
    get the whole population back. Overlap between items is fine -- this asks
    about coverage, not partition.
    """
    events = list(events)
    out = {}
    for group, items in filters.items():
        covered = {id(e) for e in events
                   if any(p(e) for p in items.values())}
        out[group] = len(covered) == len(events)
    return out


def rows(events: Iterable[Event], filters: FilterSpec,
         prefix: str = '') -> dict[str, list[Event]]:
    """The breakdown flattened to '<prefix><Group> - <Item>' -> events.

    This is the shape ``get_full_data`` reports, and the shape the golden
    regression harness keys on. ``prefix`` separates two populations reported
    side by side in one module, e.g. 'Dump-Out ' or 'Reception '.
    """
    out: dict[str, list[Event]] = {}
    for group, items in breakdown(events, filters).items():
        for item, matched in items.items():
            out[f'{prefix}{group} - {item}'] = matched
    return out


class FilterGroups:
    """One population's filter dictionary, with the operations bound to it.

    Modules keep their dictionary as the public, readable definition and wrap
    an instance of this for the behaviour::

        SHOTS = FilterGroups('shot', SHOT_FILTERS)

        def filter_shots(shots, **selections):
            return SHOTS.filter(shots, **selections)
    """

    __slots__ = ('name', 'filters')

    def __init__(self, name: str, filters: FilterSpec):
        self.name = name
        self.filters = filters

    def __repr__(self) -> str:            # pragma: no cover - debugging aid
        return f"<FilterGroups {self.name!r} groups={sorted(self.filters)}>"

    @property
    def groups(self) -> list[str]:
        return list(self.filters)

    def items(self, group: str) -> list[str]:
        """The item names in one group."""
        try:
            return list(self.filters[group])
        except KeyError:
            raise KeyError(f"unknown filter group {group!r}; "
                           f"groups are {sorted(self.filters)}") from None

    def matching(self, events: Iterable[Event], group: str, item: str) -> list[Event]:
        return matching(events, self.filters, group, item)

    def filter(self, events: Iterable[Event], **selections: Iterable[str]) -> list[Event]:
        return apply_selection(events, self.filters, **selections)

    def breakdown(self, events: Iterable[Event]) -> dict[str, dict[str, list[Event]]]:
        return breakdown(events, self.filters)

    def check_exhaustive(self, events: Iterable[Event]) -> dict[str, bool]:
        return check_exhaustive(events, self.filters)

    def rows(self, events: Iterable[Event], prefix: str = '') -> dict[str, list[Event]]:
        return rows(events, self.filters, prefix)


if __name__ == "__main__":
    # A worked example on a synthetic population -- no game data, no database,
    # so `python hockey/derive/filter_group.py` runs anywhere.

    def shot(kind: str, outcome: str, *flags: str) -> Event:
        return Event(game_id=1, t=0.0, type=kind, name='shot',
                     team_id_in_possession=10, team_id=10, player_id=7,
                     team_defencemen_on_ice_refs=None, grade=None, raw={},
                     outcome=outcome, flags=list(flags), zone='oz')

    shots = [
        shot('slot',           'successful', 'withgoal', 'withpressure'),
        shot('slot',           'successful', 'withpressure'),
        shot('outside',        'successful'),
        shot('outside',        'failed',     'screened'),
        shot('slotblocked',    'failed'),
        shot('outsideblocked', 'failed',     'withpressure'),
    ]

    # 1. A predicate is just Event -> bool.
    def is_on_net(e: Event) -> bool:      return e.outcome == 'successful'
    def is_blocked(e: Event) -> bool:     return 'blocked' in e.type
    def is_missed(e: Event) -> bool:      return not is_blocked(e) and e.outcome == 'failed'
    def is_slot(e: Event) -> bool:        return 'slot' in e.type
    def is_outside(e: Event) -> bool:     return not is_slot(e)
    def is_pressured(e: Event) -> bool:   return 'withpressure' in e.flags
    def is_unpressured(e: Event) -> bool: return not is_pressured(e)

    # 2. Group them. Each group should cover the whole population.
    SPEC: FilterSpec = {
        'Result':   {'On Net': is_on_net, 'Missed': is_missed, 'Blocked': is_blocked},
        'Location': {'Slot': is_slot, 'Outside': is_outside},
        'Pressure': {'Pressure': is_pressured, 'No Pressure': is_unpressured},
    }

    # 3. Bind the operations to the dictionary.
    SHOTS = FilterGroups('shot', SPEC)
    print(SHOTS, "\n")

    # 4. Expand every group at once.
    print("breakdown:")
    for group, items in SHOTS.breakdown(shots).items():
        print(f"   {group:9s} " + "  ".join(f"{i}={len(v)}" for i, v in items.items()))

    # 5. One named item, then a selection: OR inside a group, AND across groups.
    print("\nmatching('Result', 'Blocked')      ->", len(SHOTS.matching(shots, 'Result', 'Blocked')))
    print("filter(Result=['On Net'])          ->", len(SHOTS.filter(shots, Result=['On Net'])))
    print("filter(Result=['Missed','Blocked'])->",
          len(SHOTS.filter(shots, Result=['Missed', 'Blocked'])), "  (OR within a group)")
    print("filter(Result=[...], Location=[...])->",
          len(SHOTS.filter(shots, Result=['On Net'], Location=['Slot'])), "  (AND across groups)")
    # Underscores in a keyword stand in for spaces; a group whose name is not a
    # valid identifier is passed by unpacking instead.
    print("filter(**{'Pressure': [...]})      ->",
          len(SHOTS.filter(shots, **{'Pressure': ['Pressure']})))

    # 6. The contract: tick every item in a group and you get everything back.
    print("\nexhaustive?", SHOTS.check_exhaustive(shots))

    # A group that leaks is caught here rather than silently losing events --
    # 'Blocked' is dropped, so two shots belong to no item.
    LEAKY: FilterSpec = {'Result': {'On Net': is_on_net, 'Missed': is_missed}}
    print("leaky group:", FilterGroups('leaky', LEAKY).check_exhaustive(shots),
          "<- add a complement item ('Untagged', 'Ungraded', ...) to fix")

    # 7. The flattened shape get_full_data reports, optionally prefixed.
    print("\nrows(prefix='Shot '):")
    for key, matched in SHOTS.rows(shots, 'Shot ').items():
        print(f"   {key:28s} {len(matched)}")
