# `hockey/derive/` — metrics and filters

The computational core between `hockey/model/` and anything that displays
something. Everything here takes `Event` objects and returns `Event` objects;
nothing here knows about Flask, Plotly or the canvas.

**Two kinds of documentation live in this tree, and they are not the same
thing.** This file describes the ARCHITECTURE — how a metric module is built
and wired up. Each subfolder's `CLAUDE.md` describes the HOCKEY: what the
supplier means by "blocked pass" or "1st assist". When they disagree, the
subfolder file is the spec and this file is the mechanism.

---

## 1. The shape of a metric module

A metric module describes one or more POPULATIONS of events. A population is
all events of one supplier `name` — every `shot`, every `pass`. Each population
gets a dictionary of GROUPS; each group is a set of ITEMS; each item is one
`Event -> bool` predicate.

```python
# 1. Predicates. One per filter item. Always Event -> bool, never a list
#    filter, so groups can be combined and checked mechanically.
def is_on_net(event: Event) -> bool:
    return event.outcome == 'successful'

# 2. The dictionary. Group name -> item name -> predicate.
SHOT_FILTERS: dict[str, dict[str, Predicate]] = {
    'Result':   {'On Net': is_on_net, 'Blocked': is_blocked, ...},
    'Pressure': {'Pressure': is_pressured, 'No Pressure': is_not_pressured},
}

# 3. Bind it. The name MUST be the supplier event name -- metric_catalog
#    locates a population by it.
SHOTS = FilterGroups('shot', SHOT_FILTERS)

# 4. The base set: the whole population, optionally one team's.
def all_shots(game, team_id=None) -> list[Event]:
    events = [e for e in game.events if e.name == 'shot']
    return for_team(events, team_id) if team_id else events

# 5. Thin public wrappers, so callers never touch FilterGroups directly.
def filter_shots(shots, **selections):  return SHOTS.filter(shots, **selections)
def group_breakdown(shots):             return SHOTS.breakdown(shots)
def check_groups_exhaustive(shots):     return SHOTS.check_exhaustive(shots)

# 6. get_full_data(game) -> {team_id: {label: [events]}} -- what the golden
#    harness sweeps. 'All X' plus SHOTS.rows(shots).
```

Modules that own two populations (dumpins, DZExits, passing, defensive_events)
bind two `FilterGroups` and prefix the second one's rows: `SHOTS.rows(x)` and
`RECOVERIES.rows(x, 'Recovery ')`.

### The contract

- **OR within a group, AND across groups.** `filter_x(events, Result=['On Net'],
  Pressure=['Pressure'])` means on-net AND pressured. Groups are independent
  axes, not alternatives.
- **A group is EXHAUSTIVE**: tick every item and you get the whole population
  back. `check_groups_exhaustive()` verifies this against real games — it is
  the invariant the UI depends on.
- **Exhaustive does not mean disjoint.** Deliberate overlaps exist and are
  documented at each site: shooting's `Slot` is the union of inner and outer;
  `Led to Goal` is a subset of `On Net`; defensive `Breakaway` is a subset of
  `Odd-Man`.
- **Where a group would otherwise leak, add an explicit complement item** —
  `Untagged`, `Untyped`, `Ungraded`, `With No Shot`, `No Pressure`. Never let
  events fall out silently.
- **Read the field the supplier actually populates.** It is inconsistent
  between `type` and `flags`, and the two disagree: on a controlled entry
  `withslotshot` is on 35 events as a flag but the type spells it
  `withshotonnetandslotshot`, so substring-matching the type finds 8. Every
  module's docstring records which source it uses and the counts that prove it.

### What deliberately does NOT fit the pattern

Anything that is not an `Event -> bool` test over one population stays a plain
named function, with a docstring saying why:

- `playmaking.ogp_categories` — eight categories drawn from different event
  names; no single population to filter.
- `possession.successful_possessions` — needs the BASE event (both it and the
  possession must be successful), which a predicate cannot see.
- `playmaking.scoring_chances_goals` — the goal marker is a flag on the base
  shot, not on the chance.
- `defensive_events.dumpins_against` / `shot_pressure` — single-valued
  populations (one type, one outcome, one zone), so a group would be
  decoration rather than structure.

---

## 2. The shared machinery — `filter_group.py`

The four operations over a filter dictionary — pick one item, apply a
selection, expand every group, check exhaustiveness — are identical whatever
the population, so they live in one place and each module binds them with
`FilterGroups(name, filters)`. There is exactly one implementation of the
sweep in the repo; if you find yourself writing a second, don't.

`for_team(events, team_id)` also lives here. `rows(events, prefix='')`
produces the flat `'<Group> - <Item>' -> events` shape `get_full_data` reports.

Run `python hockey/derive/filter_group.py` for a worked example on synthetic
events, including a deliberately leaky group so you can see what
`check_exhaustive` catches.

---

## 3. The tree — `metric_catalog.py`

Assembles every module's dictionaries into the tree a UI shows:

```
SECTION  ->  POPULATION  ->  GROUP  ->  ITEM
"Entries"    "Dump-ins"      "Type"     "Chip"
```

- A LANE is one leaf: `"<population> · <item>"`, e.g. `Dump-ins · Chip`. Every
  population also gets an unfiltered `All` lane.
- **Lane keys are unique across the whole tree**, asserted at import by
  `flatten()`. A colliding item name fails loudly here rather than silently
  merging two lanes in the UI.
- **A lane key carries no section.** Regrouping sections therefore changes
  nothing but the headings — the chart, report columns and CSV headers are
  untouched. That is why `Entries` could absorb two modules for free.
- **A section is a display grouping, not an import path.** Each
  `PopulationSpec` names its own module, so one section can gather populations
  from several — `Entries` holds `controlled_entries` and `dumpins`.
- The one rule: a population appears in exactly ONE section per registry.

Currently 8 sections, 15 populations, 149 lanes. Run
`python hockey/derive/metric_catalog.py` to print the whole tree.

---

## 4. Situation filtering — `context_filter.py`

Orthogonal to the metric filters: those pick WHAT happened, this picks the
situation it happened IN. Team, period (All/P1/P2/P3/OT), manpower
(ES/SH1/SH2/PP1/PP2) and goalies (both on ice / goalie out / opponent goalie
out). Takes any iterable of events, from one game or many, and imports nothing
but `Event`.

Three rules worth knowing before you touch it:

- **The supplier wins wherever it publishes a value.** Direction is
  `raw['manpower_situation']` verbatim; period is `raw['period']`. Only what
  the supplier does not publish is derived — its manpower field is three-valued
  (`evenStrength`/`powerPlay`/`shortHanded`), so the 1-vs-2 magnitude comes
  from skater counts.
- **A pulled goalie buys an extra attacker, not an advantage.** 6v5 is EVEN
  strength and the supplier labels it so. Magnitude is computed on skaters
  minus one when that team's goalie ref is null. Verified: the adjusted
  difference agrees in sign with the supplier on 100% of 28421 uncompiled and
  99.69% of 46989 compiled events.
- **Unknowns are not guesses.** An event that cannot be classified returns
  `None` and matches no value, so it drops out of any narrowing selection
  rather than being folded into ES. ~3.5% of the uncompiled path; ~0 on
  compiled and database.

---

## 5. How the canvas consumes all this

`hockey/visualize/game_canvas.py` builds its left-hand rail from
`metric_catalog` — it holds no metric definitions of its own. Add a filter item
to a module and it appears on the canvas; there is no second list to update.

Context is classified server-side and packed into one int per event
(`period*100 + manpower*10 + goalies`) so the browser filters with no round
trip. The Team dimension is deliberately absent from the context bar — the page
already has a team selector.

**Bump `CANVAS_VERSION` whenever the generated HTML changes.** `app.py` caches
canvas HTML keyed on it, so a warm worker otherwise keeps serving the old page.

---

## 6. Verification — `hockey/regression/golden.py`

There is no test suite. This is what stands in for one:

```bash
python -m hockey.regression.golden capture     # freeze the baseline
python -m hockey.regression.golden compare     # what changed?
python -m hockey.regression.golden crosscheck --sources playsequence_compiled database
```

It sweeps every module's `get_full_data()` over 20 games × 2 sources and
records a COUNT **and a SIGNATURE** (a hash of the matched events' identities)
for each metric. The signature is the point: a refactor can easily return the
right number of the wrong events.

Two habits that make it useful:

- **Run `compare` before and after any refactor.** "IDENTICAL" is the goal;
  anything in `count_changed` or `events_changed` is a regression.
- **A renamed key shows up as removed+added, which the harness cannot
  compare.** When you rename metric labels, check the old labels against the
  new computation yourself — recompute each old label through the new API and
  compare counts AND signatures — then recapture. Don't just recapture.

---

## 7. Adding a new metric module

1. Write the hockey definitions in `<module>/CLAUDE.md` first.
2. Create `<module>/metrics.py` following §1. **Name the file `metrics.py`** —
   everything else in the tree does.
3. Resolve `Settings` lazily (`_settings()`, not a module-level call).
   `Settings.from_env` raises without `DATA_ROOT_DIR`, and the canvas imports
   these modules through the catalog, so a module-level call breaks the canvas
   in `db_only` deployments. Copy the `_settings()` helper from any sibling.
4. Verify exhaustiveness on real games and record the counts in the module
   docstring — future readers need the evidence, not the assertion.
5. **Register the populations in `metric_catalog._REGISTRY`**, or the module is
   invisible to the canvas.
6. **Add the module to `golden.py MODULES`**, or nothing protects it.
7. `capture` a new golden snapshot.

---

## 8. Known drift (as of 2026-09-16)

- **`scoring` is named `scoring.py`, not `metrics.py`.** It is registered in
  `metric_catalog._REGISTRY` and swept by `golden.py`, and behaves like every
  other module — but it is the one file in the tree that a convention-following
  glob will miss. Renaming it would rename work in progress, so it is left
  alone and named explicitly by the `SCORING` constant in the catalog.
- **Manpower is implemented twice.** `context_filter` classifies events in
  Python; `hockey/metrics/player/skater.py` reproduces the same rule in SQL for
  database aggregation, under different constant names (`FS/PP/PP2/SH/SH2`
  against `ES/PP1/PP2/SH1/SH2`). They agree by construction today — same
  supplier field, same pulled-goalie adjustment, same clamp — but they are two
  implementations and a change to one must be made to the other.
- `hockey/metrics/` is a different layer from `hockey/derive/`: it aggregates
  over many games in the database, rather than filtering one game's events.
