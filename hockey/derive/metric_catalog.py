#!/usr/bin/python
"""The metric tree, assembled from the eight ``derive/`` metric modules.

Each module describes one or more POPULATIONS of events with a ``*_FILTERS``
dictionary of exhaustive groups, bound to a :class:`~hockey.derive.filter_group
.FilterGroups` (see that module for the contract). This is the single place
that says which modules exist, what each population is called in the UI, and
which supplier event name it draws from -- so a consumer like the game canvas
builds its selector FROM the metric layer instead of keeping a second,
hand-maintained copy of the same definitions that drifts out of step.

WHAT A LANE IS. One leaf of the tree: a population plus one filter item, e.g.
"Passes · Slot". Every population also gets an unfiltered ``All`` lane. A lane
key is ``"<population> · <item>"`` and is unique across the whole tree --
:func:`lanes` asserts that at import, so adding a colliding item name fails
loudly here rather than silently merging two lanes in the UI.

WHAT IS NOT HERE. The population base sets are exactly ``event.name ==
<FilterGroups.name>`` for all thirteen populations, which is what lets this be
a lookup rather than a call into each module. Anything a module computes that
is NOT an event-level predicate over one population -- playmaking's OGP
categories, possession's base-event breakdown, the goal marker that lives on a
scoring chance's base shot -- has no lane, because the canvas can only draw
events it can test one at a time.

Event names the eight modules do not cover (goal, assist, faceoff, penalty,
icing, offside, lpr, carry, ...) contribute no lane at all: roughly a third of
a game's events. That is the intended scope of the tree, not an omission.

Importing this module must not touch the filesystem -- the canvas depends on
it, and the canvas has to work in ``db_only`` deployments where DATA_ROOT_DIR
is unset. That is why the metric modules resolve their settings lazily.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from hockey.model.events import Event
from hockey.derive.filter_group import FilterGroups, Predicate

#: Separator between a population and its item in a lane key. Also the visual
#: separator in the UI, so it is a single character that reads well in a chart
#: axis label.
SEP = " · "

#: The lane that carries a whole population, unfiltered.
ALL_ITEM = "All"

# (module label, dotted module, ((population label, supplier event name), ...))
# The event name is also the FilterGroups name each module binds, which is how
# a population is located inside its module.
_REGISTRY: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("Shooting", "hockey.derive.shooting.metrics", (
        ("Shots", "shot"),
    )),
    ("Controlled entries", "hockey.derive.controlled_entries.metrics", (
        ("Controlled entries", "controlledentry"),
    )),
    ("Dump-ins", "hockey.derive.dumpins.metrics", (
        ("Dump-ins", "dumpin"),
        ("Dump-in recoveries", "dumpinrecovery"),
    )),
    ("DZ exits", "hockey.derive.DZExits.metrics", (
        ("Controlled exits", "controlledexit"),
        ("Dump-outs", "dumpout"),
    )),
    ("Passing", "hockey.derive.passing.metrics", (
        ("Passes", "pass"),
        ("Receptions", "reception"),
    )),
    ("Playmaking", "hockey.derive.playmaking.metrics", (
        ("Scoring chances", "scoringchance"),
    )),
    ("Possession", "hockey.derive.possession.metrics", (
        ("Possessions", "possession"),
    )),
    ("Defensive events", "hockey.derive.defensive_events.metrics", (
        ("Entries against", "controlledentryagainst"),
        ("Blocks", "block"),
        ("Checks", "check"),
    )),
)


@dataclass(frozen=True)
class Lane:
    """One leaf: a population, optionally narrowed to a single filter item."""
    key: str                      # "Passes · Slot" -- unique across the tree
    module: str                   # "Passing"
    population: str               # "Passes"
    event_name: str               # "pass"
    group: str | None             # "Type"; None on the All lane
    item: str                     # "Slot", or ALL_ITEM
    predicate: Predicate | None   # None on the All lane (everything matches)

    def matches(self, event: Event) -> bool:
        return self.predicate is None or self.predicate(event)


@dataclass(frozen=True)
class PopulationTree:
    label: str
    event_name: str
    all_lane: Lane
    groups: tuple[tuple[str, tuple[Lane, ...]], ...]

    @property
    def lanes(self) -> tuple[Lane, ...]:
        return (self.all_lane,) + tuple(
            lane for _, lanes in self.groups for lane in lanes)


@dataclass(frozen=True)
class ModuleTree:
    label: str
    dotted: str
    populations: tuple[PopulationTree, ...]

    @property
    def lanes(self) -> tuple[Lane, ...]:
        return tuple(lane for pop in self.populations for lane in pop.lanes)


def _find_groups(module, event_name: str) -> FilterGroups:
    """The FilterGroups a module binds for one population."""
    for value in vars(module).values():
        if isinstance(value, FilterGroups) and value.name == event_name:
            return value
    raise LookupError(
        f"{module.__name__} binds no FilterGroups named {event_name!r}; "
        f"found {[v.name for v in vars(module).values() if isinstance(v, FilterGroups)]}")


def _build() -> tuple[ModuleTree, ...]:
    out: list[ModuleTree] = []
    for module_label, dotted, popspecs in _REGISTRY:
        module = importlib.import_module(dotted)
        pops: list[PopulationTree] = []
        for pop_label, event_name in popspecs:
            groups = _find_groups(module, event_name)
            all_lane = Lane(key=f"{pop_label}{SEP}{ALL_ITEM}", module=module_label,
                            population=pop_label, event_name=event_name,
                            group=None, item=ALL_ITEM, predicate=None)
            grouped = tuple(
                (group, tuple(
                    Lane(key=f"{pop_label}{SEP}{item}", module=module_label,
                         population=pop_label, event_name=event_name,
                         group=group, item=item, predicate=predicate)
                    for item, predicate in items.items()))
                for group, items in groups.filters.items()
            )
            pops.append(PopulationTree(label=pop_label, event_name=event_name,
                                       all_lane=all_lane, groups=grouped))
        out.append(ModuleTree(label=module_label, dotted=dotted,
                              populations=tuple(pops)))
    return tuple(out)


TREE: tuple[ModuleTree, ...] = _build()


def _flatten() -> tuple[Lane, ...]:
    flat = tuple(lane for mod in TREE for lane in mod.lanes)
    seen: dict[str, Lane] = {}
    for lane in flat:
        clash = seen.get(lane.key)
        if clash is not None:
            raise ValueError(
                f"duplicate lane key {lane.key!r}: "
                f"{clash.population}/{clash.group}/{clash.item} and "
                f"{lane.population}/{lane.group}/{lane.item}. Lane keys must be "
                f"unique -- rename one item, or the two will merge in the UI.")
        seen[lane.key] = lane
    return flat


#: Every lane, in tree order. The UI's reading order, and so its lane order.
LANES: tuple[Lane, ...] = _flatten()

#: Lane lookup by key.
BY_KEY: dict[str, Lane] = {lane.key: lane for lane in LANES}

#: Lanes grouped by supplier event name, so testing one event only runs the
#: predicates of its own population rather than all of them.
BY_EVENT: dict[str, tuple[Lane, ...]] = {}
for _lane in LANES:
    BY_EVENT.setdefault(_lane.event_name, ())
    BY_EVENT[_lane.event_name] += (_lane,)
del _lane


def lanes_for_event(event: Event) -> tuple[str, ...]:
    """Every lane key this event belongs to; empty if no module covers it.

    An event lands in its population's ``All`` lane plus one lane per matching
    filter item, so a single pass is typically in five or six lanes -- the
    groups are independent axes, not alternatives.
    """
    lanes = BY_EVENT.get(event.name)
    if not lanes:
        return ()
    return tuple(lane.key for lane in lanes if lane.matches(event))


def population_labels() -> tuple[str, ...]:
    return tuple(pop.label for mod in TREE for pop in mod.populations)


if __name__ == "__main__":
    total = 0
    for mod in TREE:
        print(f"\n{mod.label}")
        for pop in mod.populations:
            n = len(pop.lanes)
            total += n
            print(f"   {pop.label}  (event '{pop.event_name}', {n} lanes)")
            print(f"      {ALL_ITEM}")
            for group, lanes in pop.groups:
                print(f"      {group}: " + ", ".join(lane.item for lane in lanes))
    print(f"\n{len(TREE)} modules · {len(population_labels())} populations · "
          f"{total} lanes")
