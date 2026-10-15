#!/usr/bin/python
"""The metric tree, assembled from the ``derive/`` metric modules.

Each module describes one or more POPULATIONS of events with a ``*_FILTERS``
dictionary of exhaustive groups, bound to a :class:`~hockey.derive.filter_group
.FilterGroups` (see that module for the contract). This is the single place
that says which populations exist, what each is called in the UI, and which
supplier event name it draws from -- so a consumer like the game canvas builds
its selector FROM the metric layer instead of keeping a second,
hand-maintained copy of the same definitions that drifts out of step.

WHAT A LANE IS. One leaf of the tree: a population plus one filter item, e.g.
"Passes · Slot". Every population also gets an unfiltered ``All`` lane. A lane
key is ``"<population> · <item>"`` and is unique across the whole tree --
:func:`flatten` asserts that at import, so a colliding item name fails loudly
here rather than silently merging two lanes in the UI.

SECTIONS SPAN MODULES. A section is the top level of the tree, and it is a
DISPLAY grouping, not an import path: each population names its own module, so
one section can gather populations from several modules. "Entries" below is
the worked example -- it holds ``controlled_entries`` and ``dumpins`` side by
side, and neither module knows about the other. Nothing in ``hockey/derive/``
was merged to make that work: ``FilterGroups`` carries no module identity, so
it is simply looked up in a different file.

Because a lane key is ``population · item`` and carries no section, regrouping
sections changes only :attr:`Lane.section`. Every lane key, and so the chart,
the report columns and the CSV headers, is unaffected by how sections are
arranged -- only the selector's grouping moves.

The one rule: within a single registry a population must appear in exactly one
section. Listing the same population twice collides on its keys --
deliberately, because two checkboxes sharing a key would not stay in sync.

WHAT A LANE MEANS IS NOT HERE EITHER. A lane carries its name and its
predicate; the sentence explaining it to someone who did not choose it lives
in ``lane_docs.py`` and its JSON file, reached through :attr:`Lane.description`
and loaded lazily so that importing this module still touches no filesystem.
Prose has a different author and a different review from a predicate, and the
``*_FILTERS`` contract is group -> item -> predicate for all fifteen modules.

WHAT IS NOT HERE. The population base sets are exactly ``event.name ==
<FilterGroups.name>`` for every population, which is what lets this be a lookup
rather than a call into each module. Anything a module computes that is NOT an
event-level predicate over one population -- playmaking's OGP categories,
possession's base-event breakdown, the goal marker that lives on a scoring
chance's base shot -- has no lane, because a consumer can only draw events it
can test one at a time. ``OZEntries`` was absent for the same reason -- it
returns ``ZoneEntry`` dataclasses, not ``Event -> bool`` predicates -- and now
lives in ``hockey/metrics/OZEntries/`` rather than under ``derive/``, since
what it does is assemble entries rather than filter events.

Event names no module covers (goal, assist, faceoff, penalty, icing, offside,
lpr, carry, ...) contribute no lane at all: roughly a third of a game's events.
That is the intended scope of the tree, not an omission.

Importing this module must not touch the filesystem -- the canvas depends on
it, and the canvas has to work in ``db_only`` deployments where DATA_ROOT_DIR
is unset. That is why the metric modules resolve their settings lazily.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from hockey.model.events import Event
from hockey.derive.filter_group import (ALL_ITEM, SEP, FilterGroups,
                                        Predicate, lane_key)

# SEP and ALL_ITEM are imported from filter_group, which is also what
# FilterGroups.rows() builds its keys with -- so the lane key a consumer reads
# and the label the golden harness records are one string, not two schemes for
# the same metric.

# Module paths. The _MODULE suffix is not noise: `DUMPINS` here used to be
# the dotted path while `dumpins.DUMPINS` is the FilterGroups, so one name
# meant two things depending on which file you were reading.
SHOOTING_MODULE = "hockey.derive.shooting.metrics"
# The one module not called metrics.py. Left at its own name rather than
# renamed underneath work in progress; see the drift note in CLAUDE.md.
SCORING_MODULE = "hockey.derive.scoring.scoring"
CONTROLLED_ENTRIES_MODULE = "hockey.derive.controlled_entries.metrics"
DUMPINS_MODULE = "hockey.derive.dumpins.metrics"
DZ_EXITS_MODULE = "hockey.derive.DZExits.metrics"
PASSING_MODULE = "hockey.derive.passing.metrics"
PLAYMAKING_MODULE = "hockey.derive.playmaking.metrics"
POSSESSION_MODULE = "hockey.derive.possession.metrics"
DEFENSIVE_EVENTS_MODULE = "hockey.derive.defensive_events.metrics"
FACEOFFS_MODULE = "hockey.derive.faceoffs.metrics"
LPR_MODULE = "hockey.derive.lpr.metrics"

@dataclass(frozen=True)
class PopulationSpec:
    """One population: where to find it. What it is CALLED lives with it.

    ``module`` is the dotted path of the metric module that binds the
    FilterGroups; ``event_name`` is the supplier event name, which is also the
    name that FilterGroups was bound under and how it is located.

    There is deliberately no label here. The population's label is
    ``FilterGroups.label``, set where the population is defined, so the
    registry cannot drift from the module and one metric keeps one name.
    """
    module: str
    event_name: str


@dataclass(frozen=True)
class SectionSpec:
    """A display grouping of populations, which may come from several modules."""
    label: str
    populations: tuple[PopulationSpec, ...]


#: The live tree. "Entries" gathers populations from two modules; the other
#: sections happen to line up one-to-one with a module, which is a convenience
#: rather than a constraint.
_REGISTRY: tuple[SectionSpec, ...] = (
    SectionSpec("Scoring", (
        PopulationSpec(SCORING_MODULE, "goal"),
        PopulationSpec(SCORING_MODULE, "assist"),
    )),
    SectionSpec("Shooting", (
        PopulationSpec(SHOOTING_MODULE, "shot"),
    )),
    SectionSpec("Entries", (
        PopulationSpec(CONTROLLED_ENTRIES_MODULE, "controlledentry"),
        PopulationSpec(DUMPINS_MODULE, "dumpin"),
        # 1:1 with the dump-in, and the event whose outcome says the dumping
        # team recovered -- so its Successful share is a true recovery rate,
        # which "Dump-ins · Successful" (a depth criterion) is not.
        PopulationSpec(DUMPINS_MODULE, "dumpinentry"),
        PopulationSpec(DUMPINS_MODULE, "dumpinrecovery"),
    )),
    SectionSpec("DZ exits", (
        PopulationSpec(DZ_EXITS_MODULE, "controlledexit"),
        PopulationSpec(DZ_EXITS_MODULE, "dumpout"),
    )),
    SectionSpec("Passing", (
        PopulationSpec(PASSING_MODULE, "pass"),
        PopulationSpec(PASSING_MODULE, "reception"),
    )),
    SectionSpec("Playmaking", (
        PopulationSpec(PLAYMAKING_MODULE, "scoringchance"),
    )),
    SectionSpec("Possession", (
        PopulationSpec(POSSESSION_MODULE, "possession"),
    )),
    SectionSpec("Faceoffs", (
        PopulationSpec(FACEOFFS_MODULE, "faceoff"),
    )),
    SectionSpec("Lpr", (
        PopulationSpec(LPR_MODULE, "lpr"),
    )),
    SectionSpec("Defensive events", (
        PopulationSpec(DEFENSIVE_EVENTS_MODULE, "controlledentryagainst"),
        PopulationSpec(DEFENSIVE_EVENTS_MODULE, "block"),
        PopulationSpec(DEFENSIVE_EVENTS_MODULE, "check"),
    )),
)


@dataclass(frozen=True)
class Lane:
    """One leaf: a population, optionally narrowed to a single filter item."""
    key: str                      # "Passes · Slot" -- unique across the tree
    section: str                  # "Passing" -- the display grouping
    population: str               # "Passes"
    event_name: str               # "pass"
    group: str | None             # "Type"; None on the All lane
    item: str                     # "Slot", or ALL_ITEM
    predicate: Predicate | None   # None on the All lane (everything matches)

    def matches(self, event: Event) -> bool:
        return self.predicate is None or self.predicate(event)

    # The description is a PROPERTY, not a field: it is prose about the lane
    # rather than part of its identity, it is written and reviewed by whoever
    # knows the hockey rather than by whoever binds the predicates, and
    # reading it must not happen while this module is being imported. See
    # lane_docs for all three reasons. Empty until someone writes it.

    @property
    def description(self) -> str:
        """One sentence a selector can show, or "" if nobody has written it."""
        from hockey.derive import lane_docs
        return lane_docs.for_lane(self)

    @property
    def description_source(self) -> str:
        """Whether that sentence is this lane's own or borrowed by item name."""
        from hockey.derive import lane_docs
        return lane_docs.source_for(self)


@dataclass(frozen=True)
class PopulationTree:
    label: str
    event_name: str
    module: str
    all_lane: Lane
    groups: tuple[tuple[str, tuple[Lane, ...]], ...]

    @property
    def lanes(self) -> tuple[Lane, ...]:
        return (self.all_lane,) + tuple(
            lane for _, lanes in self.groups for lane in lanes)


@dataclass(frozen=True)
class SectionTree:
    label: str
    populations: tuple[PopulationTree, ...]

    @property
    def lanes(self) -> tuple[Lane, ...]:
        return tuple(lane for pop in self.populations for lane in pop.lanes)

    @property
    def modules(self) -> tuple[str, ...]:
        """The distinct modules this section draws on, in first-seen order."""
        return tuple(dict.fromkeys(pop.module for pop in self.populations))


def _find_groups(module, event_name: str) -> FilterGroups:
    """The FilterGroups a module binds for one population."""
    for value in vars(module).values():
        if isinstance(value, FilterGroups) and value.name == event_name:
            return value
    raise LookupError(
        f"{module.__name__} binds no FilterGroups named {event_name!r}; "
        f"found {[v.name for v in vars(module).values() if isinstance(v, FilterGroups)]}")


def build_tree(registry: tuple[SectionSpec, ...]) -> tuple[SectionTree, ...]:
    """Resolve a registry into the tree, importing each population's module.

    Parameterised rather than hard-wired to :data:`_REGISTRY` so an alternative
    grouping can be built and inspected without disturbing the live one.
    """
    out: list[SectionTree] = []
    for section in registry:
        pops: list[PopulationTree] = []
        for spec in section.populations:
            module = importlib.import_module(spec.module)   # importlib caches
            groups = _find_groups(module, spec.event_name)
            # The label comes from the population itself, not from the
            # registry, and lane_key is the same function FilterGroups.rows
            # builds its keys with -- so a lane has one name everywhere.
            label = groups.label
            all_lane = Lane(key=lane_key(label), section=section.label,
                            population=label, event_name=spec.event_name,
                            group=None, item=ALL_ITEM, predicate=None)
            grouped = tuple(
                (group, tuple(
                    Lane(key=lane_key(label, item), section=section.label,
                         population=label, event_name=spec.event_name,
                         group=group, item=item, predicate=predicate)
                    for item, predicate in items.items()))
                for group, items in groups.filters.items()
            )
            pops.append(PopulationTree(label=label, event_name=spec.event_name,
                                       module=spec.module, all_lane=all_lane,
                                       groups=grouped))
        out.append(SectionTree(label=section.label, populations=tuple(pops)))
    return tuple(out)


def flatten(tree: tuple[SectionTree, ...]) -> tuple[Lane, ...]:
    """Every lane in tree order, asserting that lane keys are unique."""
    flat = tuple(lane for section in tree for lane in section.lanes)
    seen: dict[str, Lane] = {}
    for lane in flat:
        clash = seen.get(lane.key)
        if clash is not None:
            raise ValueError(
                f"duplicate lane key {lane.key!r}: "
                f"{clash.section}/{clash.population}/{clash.item} and "
                f"{lane.section}/{lane.population}/{lane.item}. Lane keys must "
                f"be unique -- a population belongs to exactly one section, or "
                f"the two would merge in the UI.")
        seen[lane.key] = lane
    return flat


TREE: tuple[SectionTree, ...] = build_tree(_REGISTRY)

#: Every lane, in tree order. The UI's reading order, and so its lane order.
LANES: tuple[Lane, ...] = flatten(TREE)

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
    return tuple(pop.label for section in TREE for pop in section.populations)


def print_tree(tree: tuple[SectionTree, ...]) -> int:
    total = 0
    for section in tree:
        modules = section.modules
        suffix = f"   [{len(modules)} modules]" if len(modules) > 1 else ""
        print(f"\n{section.label}{suffix}")
        for pop in section.populations:
            n = len(pop.lanes)
            total += n
            print(f"   {pop.label}  (event '{pop.event_name}', {n} lanes, "
                  f"{pop.module.rsplit('.', 2)[-2]})")
            print(f"      {ALL_ITEM}")
            for group, lanes in pop.groups:
                print(f"      {group}: " + ", ".join(lane.item for lane in lanes))
    return total


if __name__ == "__main__":
    total = print_tree(TREE)
    print(f"\n{len(TREE)} sections · {len(population_labels())} populations · "
          f"{total} lanes")
    spanning = [f"{s.label} ({len(s.modules)})" for s in TREE if len(s.modules) > 1]
    print(f"sections drawing on more than one module: {spanning or 'none'}")
