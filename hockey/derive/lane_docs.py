#!/usr/bin/python
"""Human descriptions for the metric tree, kept out of the metric modules.

WHAT THIS IS FOR. The catalog knows a lane's NAME -- "LPRs · Is Not Rebound"
-- and nothing about what it means. That is enough for a report column read by
someone who chose it, and nowhere near enough for a selector handed to a coach
who is browsing 171 of them. This is where the sentence that tells him lives.

WHY NOT IN THE ``*_FILTERS`` DICTIONARIES. Their contract is group -> item ->
``Event -> bool`` and one implementation reads it for all fifteen modules
(``filter_group.py``). Turning a value into ``(predicate, description)`` would
change that contract everywhere, for prose -- so the prose sits beside the
tree in ``lane_descriptions.json`` instead, keyed by the lane keys the catalog
already guarantees are unique. No predicate, count or signature is touched by
anything in this module, which is why ``golden.py`` cannot notice it.

IT IS ALSO WHERE A NON-PROGRAMMER CAN WRITE. One flat JSON file of keys and
sentences: fillable by whoever knows the hockey, without reading Python, and
reviewable in a diff.

NOTHING HERE IS INFERRED FROM A PREDICATE. The file ships with every key the
catalog can produce and an empty string for each, and only the entries the
repository already states somewhere are filled in. An empty description is an
honest "nobody has written this yet"; a guessed one would be a sentence a
coach believes. :func:`coverage` is the worklist.

RESOLUTION, for one lane:

1. ``lanes[<lane key>]``  -- the exact sentence for this lane
2. ``items[<item name>]`` -- a shared sentence for an item name that appears in
   several populations ("Successful" is in nine), so it is written once
3. ``""``                 -- not written yet

:func:`source_for` says which of those answered, because a UI should be able
to show a generic sentence differently from a specific one -- "Successful"
means something subtly different for a pass and for a dump-in recovery, and
the catalog itself records one such trap (``Dump-in entries``' successful
share is a true recovery rate; ``Dump-ins · Successful`` is a depth criterion).

LOADED LAZILY, NEVER AT IMPORT. ``metric_catalog`` must stay importable
without touching the filesystem -- the game canvas depends on it and has to
work in ``db_only`` deployments -- so the file is read on first access and a
missing or broken one degrades to no descriptions with a warning, rather than
breaking the canvas over prose.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

#: Beside the catalog it describes, and shipped with the package the way
#: ``manifests/`` and ``config/team_colors.json`` are.
PATH = Path(__file__).resolve().parent / "lane_descriptions.json"

_EMPTY: dict[str, dict[str, str]] = {"populations": {}, "groups": {},
                                     "items": {}, "lanes": {}}
_CACHE: dict[str, dict[str, str]] | None = None

#: Which level of the file answered. A UI can grey a generic sentence.
EXACT, GENERIC, NONE = "lane", "item", ""


def _load() -> dict[str, dict[str, str]]:
    """The file, read once. Any failure is a warning and no descriptions."""
    global _CACHE
    if _CACHE is None:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8"))
            _CACHE = {section: dict(raw.get(section) or {})
                      for section in _EMPTY}
        except (OSError, ValueError) as problem:
            warnings.warn(f"{PATH.name}: {problem}; the metric tree will show "
                          f"no descriptions", stacklevel=3)
            _CACHE = dict(_EMPTY)
    return _CACHE


def reload() -> None:
    """Forget the cached file, so an edit shows up without a restart."""
    global _CACHE
    _CACHE = None


def for_lane(lane) -> str:
    """One lane's description, by the resolution order in the module docstring.

    Takes a :class:`~hockey.derive.metric_catalog.Lane` or anything carrying a
    ``key`` and an ``item``, so a report column can ask too.
    """
    data = _load()
    exact = data["lanes"].get(lane.key, "").strip()
    if exact:
        return exact
    return data["items"].get(getattr(lane, "item", ""), "").strip()


def source_for(lane) -> str:
    """:data:`EXACT`, :data:`GENERIC` or :data:`NONE` for this lane."""
    data = _load()
    if data["lanes"].get(lane.key, "").strip():
        return EXACT
    if data["items"].get(getattr(lane, "item", ""), "").strip():
        return GENERIC
    return NONE


def for_population(label: str) -> str:
    """What this population is -- "every shot attempt", and so on."""
    return _load()["populations"].get(label, "").strip()


def for_group(population: str, group: str) -> str:
    """What the axis a group divides is: "Result" is how the shot ended."""
    from hockey.derive.filter_group import lane_key
    return _load()["groups"].get(lane_key(population, group), "").strip()


# --- The worklist ----------------------------------------------------------

def coverage() -> dict:
    """What is described and what is not, per population.

    The report a GUI owner wants before showing the tree to anyone: which
    lanes would appear with no explanation, and which would show a sentence
    borrowed from another population rather than their own.
    """
    from hockey.derive import metric_catalog as catalog

    per_population: dict[str, dict] = {}
    for section in catalog.TREE:
        for pop in section.populations:
            exact, generic, missing = [], [], []
            for lane in pop.lanes:
                {EXACT: exact, GENERIC: generic, NONE: missing}[
                    source_for(lane)].append(lane.key)
            per_population[pop.label] = {
                "section": section.label,
                "described": bool(for_population(pop.label)),
                "exact": exact, "generic": generic, "missing": missing,
                "groups_missing": [group for group, _ in pop.groups
                                   if not for_group(pop.label, group)],
            }
    lanes = len(catalog.LANES)
    exact_total = sum(len(p["exact"]) for p in per_population.values())
    generic_total = sum(len(p["generic"]) for p in per_population.values())
    return {"lanes": lanes, "exact": exact_total, "generic": generic_total,
            "missing": lanes - exact_total - generic_total,
            "populations": per_population}


def print_coverage() -> None:
    report = coverage()
    print(f"\n{PATH}")
    print(f"{report['lanes']} lanes: {report['exact']} described, "
          f"{report['generic']} generic, {report['missing']} missing\n")
    print(f"{'population':26s} {'pop?':5s} {'exact':>6s} {'generic':>8s} "
          f"{'missing':>8s}  groups still missing")
    print("-" * 100)
    for label, entry in report["populations"].items():
        groups = ", ".join(entry["groups_missing"])
        print(f"{label:26s} {'yes' if entry['described'] else 'NO':5s} "
              f"{len(entry['exact']):6d} {len(entry['generic']):8d} "
              f"{len(entry['missing']):8d}  "
              f"{groups[:44] + ('...' if len(groups) > 44 else '')}")
    print("\nFill them in at the path above; one sentence per key, plain "
          "hockey.\nNothing else has to change -- Lane.description reads it.")


if __name__ == "__main__":
    print_coverage()
