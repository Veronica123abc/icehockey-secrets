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

# 3. Bind it. Three arguments, each load-bearing: the SUPPLIER's event name
#    (metric_catalog locates a population by it), the dictionary, and the
#    population's LABEL -- which opens every lane key it owns, so it is the
#    one name the catalog, canvas, reports and golden snapshot all use.
SHOTS = FilterGroups('shot', SHOT_FILTERS, 'Shots')

# 4. The base set: the whole population, optionally one team's.
def all_shots(game, team_id=None) -> list[Event]:
    events = [e for e in game.events if e.name == 'shot']
    return for_team(events, team_id) if team_id else events

# 5. check_groups_exhaustive -- the evidence for the docstring's counts, and
#    what the module's __main__ re-verifies. Write this one.
def check_groups_exhaustive(shots):     return SHOTS.check_exhaustive(shots)

# 6. get_full_data(game) -> {team_id: {lane key: [events]}} -- what the golden
#    harness sweeps. Just SHOTS.rows(shots): it emits the All lane too, and
#    its keys ARE lane keys.
```

**One metric, one name.** `FilterGroups.rows` and `metric_catalog` both build
keys with `filter_group.lane_key`, so `"Shots · On Net"` is what the canvas
checkbox, the report column, `game_metrics` and the golden snapshot all call
it. They did not used to: `rows()` invented `"<prefix><Group> - <Item>"`, so
the same number was `'Entry Result - Successful'` to the harness and
`'Dump-in entries · Successful'` to everyone else, and a `prefix` argument
existed only to keep two populations in one module apart — which the label
now does. A metric that is deliberately NOT a lane (see below) keeps its own
descriptive label; it has no second name to collide with.

**Do NOT add a per-population wrapper for every FilterGroups method.** This
tree used to prescribe a `<population>_matching`, a `filter_<population>` and
a `<population>_group_breakdown` beside each binding, "so callers never touch
FilterGroups directly". The callers never arrived: 37 of them were deleted
with nothing pointing at them, including all fourteen `*_matching` and all
nine `group_breakdown`. Consumers reach a metric through the catalog
(`lane.matches`), not through a module's aliases, and the one place that does
want the raw method — `golden.py`'s `crosspath` — calls
`FilterGroups.matching` directly and is better for it.

Write a `filter_<population>` only when something calls it. Four do today,
each used by its own module or by `skater.py`; `filter_shots` is the only one
reaching outside `derive/`.

Modules that own several populations (dumpins has three; DZExits, passing and
defensive_events have two) bind one `FilterGroups` each and simply merge their
rows — `{**DUMPINS.rows(a), **DUMPIN_ENTRIES.rows(b), **RECOVERIES.rows(c)}`.
No prefixes: each population's label already opens its own keys.

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

Events are not the only thing with a situation. A shift is an interval and
carries none of those supplier fields, so the rules are also exposed over
plain numbers — `period_from_time`, `manpower_from_skaters`,
`goalies_from_flags` — with `ContextFilter.matches_situation` as the selection
itself. `matches(event)` classifies and then delegates to it, so "selected"
means one thing however it is asked. That is what lets
`metrics/player/skater.py` narrow a TOI denominator to match the events it is
counting.

Two asymmetries worth knowing before relying on it. Direction for an event
comes from the supplier; for a slice of ice time it has to be derived from the
skater counts, and the two agree in sign on 99.69% of compiled events. And
everything is relative to a team: one slice is PP1 for one bench and SH1 for
the other, so anything crediting both sides has to ask per team rather than
once.

---

## 5. Who consumes all this

Two things do, and neither defines a metric of its own.

**`hockey/visualize/game_canvas.py`** builds its left-hand rail from
`metric_catalog`. Add a filter item to a module and it appears on the canvas;
there is no second list to update.

Below the ticked lanes it draws two more: the UNION of the selection
(`ANY (472)`) and its INTERSECTION (`ALL (40)`), labelled with the count that
went into each. They are **not** lanes in this sense -- no population, no
predicate, nothing to register here, and no key that could collide in
`flatten()`. They are a reading of whatever is
ticked, computed in the browser as set operations over per-event ids, which
works precisely because an event belongs to several lanes at once: ticking
`LPRs · Successful` and `LPRs · Is Contested` intersects in the successful
contested recoveries. Across populations the intersection is empty by
construction -- a group is exhaustive over ONE population -- and that is the
honest answer rather than a bug.

**`hockey/metrics/player/skater.py`** is the same numbers without the GUI: one
line per skater over a set of games, for prototyping. It calls the metric
modules directly — `scoring.all_goals`, `shooting.filter_shots(shots,
Result=['On Net'])` — so "shots on net" means there exactly what it means on
the canvas rail. That is the pattern to copy for any new consumer: read the
metric from `derive/`, and put only the aggregating in `metrics/`.

It consumes `GameData` — one game's events, shifts and roster — rather than
`Game` objects, so where the data came from is not its concern. Two adapters
supply them: `from_games` for built games, and `from_database` for a bulk read
of `event`/`shift`/`affiliation`. Over the golden twenty the database path
takes 0.85s and 11MB against 22.3s and 75MB for building the games, and the
two agree on all 283 skaters with no field differing — which is the property
that makes the seam worth having.

`GameData` exposes `.events` under that name deliberately, so the base-set
helpers here (`scoring.all_goals(data)`) accept it and the population
definitions stay in the metric modules.

Bundles are consumed one at a time and dropped, so peak memory is flat at
~73MB on the file path whether it is two games or fifty — callers pass a
generator, not a list.

A game the database does not hold is skipped and named in a warning rather
than quietly read from files: a silent fallback would make a season's numbers
depend on which machine ran it. "Holds" means events AND shifts, because
events alone would produce a full set of counts against no ice time.

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
python -m hockey.regression.golden crosspath   # do both access paths agree?
```

It sweeps every module's `get_full_data()` over 20 games × 2 sources and
records a COUNT **and a SIGNATURE** (a hash of the matched events' identities)
for each metric. The signature is the point: a refactor can easily return the
right number of the wrong events.

**What `capture`/`compare` does NOT cover, and why `crosspath` exists.** The
sweep calls `get_full_data`, which reaches the predicates through a module's
base set and `FilterGroups.matching`. No consumer does that: the canvas, the
reports and `game_metrics` all go through `catalog.lanes_for_event`
(`BY_EVENT` + `Lane.matches`), which a sweep instrumented over two games calls
**0 times**. The two paths share only the predicates, so the snapshot protects
what anyone sees only if they agree — and nothing asserted that until
`crosspath`. Demonstrated: deleting `shot` from `BY_EVENT` zeroes every shot
lane on the canvas and in every report without touching a predicate; `compare`
says IDENTICAL, `crosspath` flags all 17 shot lanes. Run `crosspath` after
touching the catalog, a base set, or a `get_full_data`.

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
3. Resolve `Settings` lazily — `from hockey.config.settings import settings
   as _settings`, never a module-level `Settings.from_env(...)`.
   `Settings.from_env` raises without `DATA_ROOT_DIR`, and the canvas imports
   these modules through the catalog, so an eager call breaks the canvas in
   `db_only` deployments. **Import the shared accessor; do not write a local
   helper.** Every module used to carry its own 13-line copy — one constraint,
   ten implementations — which is exactly the duplication this tree exists to
   avoid elsewhere. A SCRIPT is different: something that genuinely needs
   `DATA_ROOT_DIR` should keep the eager one-liner and die at startup without
   it.
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
Resolved, and recorded so they are not reintroduced:

- Manpower used to be implemented twice, once in `context_filter` and again in
  SQL inside `skater.py`, under different constant names. `skater.py` is now
  event-based and calls the derive modules, so there is one implementation.
- `skater_stats` used to refuse a `context`, because narrowing events without
  narrowing TOI would rate a full game's events against a partial denominator.
  It now narrows both — events through `ContextFilter.matches`, ice time
  through a sweep that classifies every shift slice from each team's side.
  Checked by partition: ES+SH1+SH2+PP1+PP2 sums to each player's total TOI
  exactly, and selecting every value reproduces the unfiltered figure.
