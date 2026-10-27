#!/usr/bin/python
"""Golden-output regression harness for the derive/ metrics.

There is no test suite in this repo, so a refactor that touches many call
sites has nothing to check itself against. This captures what every metric
module reports for a fixed set of games, freezes it to disk, and diffs a later
run against it.

    python -m hockey.regression.golden capture            # write the baseline
    ... refactor ...
    python -m hockey.regression.golden compare            # what changed?

A third source, "database", loads the game through build_game_from_db instead
of the JSON files, so the same metrics can be swept over either backing store:

    python -m hockey.regression.golden crosscheck \
        --sources playsequence_compiled database --db-name hockey_v2_test

``crosscheck`` is the one that tests the loaders against each other rather
than against a frozen file: it sweeps both sources in one run and asserts they
agree metric for metric. A "compare" says "I changed nothing since last
time"; a "crosscheck" says "these two ways of loading a game agree".

    python -m hockey.regression.golden crosspath          # do the two paths agree?

``crosspath`` closes the blind spot the other two share. Everything above
sweeps ``get_full_data``, which reaches the predicates through a module's own
base set and ``FilterGroups.matching``. NOTHING IN PRODUCTION GOES THAT WAY:
the canvas, the reports and ``game_metrics`` all use
``catalog.lanes_for_event`` -- the ``BY_EVENT`` index plus ``Lane.matches`` --
and a sweep instrumented over two games calls those 0 times. So the snapshot
protects what anyone actually sees only if the two paths agree, and until
``crosspath`` nothing asserted that. Deleting 'shot' from ``BY_EVENT`` zeroes
every shot lane on the canvas and in every report while touching no
predicate; ``compare`` reports IDENTICAL, and ``crosspath`` flags all 17 shot
lanes. Run it after touching the catalog, a base set, or ``get_full_data``.

Each metric records a COUNT and a SIGNATURE -- a hash over the identities of
the matched events. The signature is what makes this useful: a refactor can
easily return the right number of the wrong events, and a count alone would
not notice.

Event identity prefers the supplier's event_id. ``playsequence.json`` carries
no per-event id, so there it falls back to (game_time, name, type, player_id),
which is not guaranteed unique -- signatures are still comparable run to run,
which is all the harness needs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Iterable
from pathlib import Path

from hockey.config.settings import Settings
from hockey.catalog.data_catalog import DataCatalog
from hockey.io.raw_game import RawGame
from hockey.model.events import Event
from hockey.normalize.build_game import build_game

settings = Settings.from_env(project_root=Path(__file__).resolve().parents[2])

DEFAULT_SNAPSHOT = Path(__file__).resolve().parent / "golden.json"

# Modules whose get_full_data() we sweep. The flag says whether it wants the
# RawGame as a second argument.
MODULES: list[tuple[str, str, bool]] = [
    ('controlled_entries', 'hockey.derive.controlled_entries.metrics', False),
    ('defensive_events',   'hockey.derive.defensive_events.metrics',   False),
    ('dumpins',            'hockey.derive.dumpins.metrics',            False),
    ('DZExits',            'hockey.derive.DZExits.metrics',            False),
    ('faceoffs',           'hockey.derive.faceoffs.metrics',           False),
    ('lpr',                'hockey.derive.lpr.metrics',                False),
    ('passing',            'hockey.derive.passing.metrics',            False),
    ('playmaking',         'hockey.derive.playmaking.metrics',         False),
    ('possession',         'hockey.derive.possession.metrics',         False),
    ('scoring',            'hockey.derive.scoring.scoring',            False),
    ('shooting',           'hockey.derive.shooting.metrics',           False),
]

SOURCES = ('playsequence_compiled', 'playsequence')
DATABASE_SOURCE = 'database'
ALL_SOURCES = SOURCES + (DATABASE_SOURCE,)


def event_identity(event: Event) -> str:
    """A stable identity for one event, for signature purposes."""
    raw_id = event.get_raw('event_id')
    if raw_id is not None:
        return str(raw_id)
    return f"{event.t:.4f}|{event.name}|{event.type}|{event.player_id}"


def signature(events: Iterable[Event]) -> str:
    """Order-independent hash of a metric's matched events."""
    ids = sorted(event_identity(e) for e in events)
    return hashlib.sha1("\n".join(ids).encode()).hexdigest()[:16]


def _load_module(dotted: str):
    import importlib
    return importlib.import_module(dotted)


def _load(game_id: int, source: str, conn=None):
    """Build one Game from the named source."""
    if source == DATABASE_SOURCE:
        if conn is None:
            raise RuntimeError("the 'database' source needs a connection")
        from hockey.normalize.build_game_db import build_game_from_db
        return build_game_from_db(game_id, conn), None
    raw = RawGame(game_id=game_id, root_dir=settings.data_root_dir,
                  playsequence_source=source)
    return build_game(raw), raw


def collect_game(game_id: int, source: str, conn=None) -> dict[str, dict]:
    """Every metric for one game under one source, as flat keys."""
    game, raw = _load(game_id, source, conn)
    out: dict[str, dict] = {}
    for label, dotted, wants_raw in MODULES:
        try:
            module = _load_module(dotted)
            res = module.get_full_data(game, raw) if wants_raw else module.get_full_data(game)
        except Exception as exc:                      # a broken module must not
            out[f"{label}/!error"] = {                # abort the whole sweep
                'error': f"{type(exc).__name__}: {exc}",
            }
            continue
        for team_id, metrics in res.items():
            for metric, events in metrics.items():
                events = list(events)
                out[f"{label}/{team_id}/{metric}"] = {
                    'n': len(events),
                    'sig': signature(events),
                }
    return out


def capture(game_ids: Iterable[int], sources: Iterable[str] = SOURCES,
            conn=None) -> dict:
    snapshot = {
        'meta': {
            'created': time.strftime('%Y-%m-%d %H:%M:%S'),
            'games': list(game_ids),
            'sources': list(sources),
        },
        'results': {},
    }
    for source in sources:
        for game_id in game_ids:
            try:
                per_game = collect_game(game_id, source, conn)
            except Exception as exc:
                snapshot['results'][f"{source}/{game_id}/!load_error"] = {
                    'error': f"{type(exc).__name__}: {exc}"}
                continue
            for key, value in per_game.items():
                snapshot['results'][f"{source}/{game_id}/{key}"] = value
    return snapshot


def diff(old: dict, new: dict) -> dict[str, list]:
    """Compare two snapshots' results, bucketed by kind of change."""
    a, b = old['results'], new['results']
    report: dict[str, list] = {
        'count_changed': [], 'events_changed': [], 'removed': [],
        'added': [], 'errors_new': [], 'errors_fixed': [],
    }
    for key in sorted(set(a) | set(b)):
        va, vb = a.get(key), b.get(key)
        if va is None:
            (report['errors_new'] if 'error' in vb else report['added']).append((key, vb))
        elif vb is None:
            report['removed'].append((key, va))
        elif 'error' in va or 'error' in vb:
            if 'error' in vb and 'error' not in va:
                report['errors_new'].append((key, vb))
            elif 'error' in va and 'error' not in vb:
                report['errors_fixed'].append((key, va))
        elif va['n'] != vb['n']:
            report['count_changed'].append((key, va, vb))
        elif va['sig'] != vb['sig']:
            report['events_changed'].append((key, va, vb))
    return report


def print_diff(report: dict[str, list], limit: int = 25,
               clean_message: str = "IDENTICAL — every metric matches the golden snapshot.") -> bool:
    """Print the diff; return True when the two sides match."""
    order = ['count_changed', 'events_changed', 'errors_new', 'removed',
             'added', 'errors_fixed']
    clean = all(not report[k] for k in ('count_changed', 'events_changed',
                                        'errors_new', 'removed'))
    for kind in order:
        rows = report[kind]
        if not rows:
            continue
        print(f"\n{kind}  ({len(rows)})")
        for row in rows[:limit]:
            if kind == 'count_changed':
                key, va, vb = row
                print(f"   {key}\n       n {va['n']} -> {vb['n']}")
            elif kind == 'events_changed':
                key, va, vb = row
                print(f"   {key}\n       same count ({va['n']}) but different events"
                      f"  {va['sig']} -> {vb['sig']}")
            else:
                key, value = row
                print(f"   {key}  {value}")
        if len(rows) > limit:
            print(f"   ... {len(rows) - limit} more")
    if clean:
        print(f"\n{clean_message}")
    return clean


def crosscheck(snapshot: dict, source_a: str, source_b: str) -> dict[str, list]:
    """Compare two sources within one snapshot, metric for metric.

    Keys are "<source>/<game>/<module>/<team>/<metric>", so dropping the
    leading source segment lines the two sweeps up.
    """
    def strip(source: str) -> dict[str, dict]:
        prefix = f"{source}/"
        return {k[len(prefix):]: v for k, v in snapshot['results'].items()
                if k.startswith(prefix)}

    a, b = strip(source_a), strip(source_b)
    report: dict[str, list] = {
        'count_changed': [], 'events_changed': [], 'removed': [],
        'added': [], 'errors_new': [], 'errors_fixed': [],
    }
    # Only games both sources produced are comparable; a game absent from one
    # is a coverage gap, not a disagreement, so report it separately.
    games_a = {k.split('/')[0] for k in a}
    games_b = {k.split('/')[0] for k in b}
    shared = games_a & games_b
    report['only_in_a'] = sorted(games_a - games_b)
    report['only_in_b'] = sorted(games_b - games_a)

    for key in sorted(set(a) | set(b)):
        if key.split('/')[0] not in shared:
            continue
        va, vb = a.get(key), b.get(key)
        if va is None:
            report['added'].append((key, vb))
        elif vb is None:
            report['removed'].append((key, va))
        elif 'error' in va or 'error' in vb:
            report['errors_new'].append((key, vb if 'error' in vb else va))
        elif va['n'] != vb['n']:
            report['count_changed'].append((key, va, vb))
        elif va['sig'] != vb['sig']:
            report['events_changed'].append((key, va, vb))
    return report


def _lane_events_by_path(game) -> tuple[dict[str, list], dict[str, list]]:
    """One game's lanes computed BOTH ways: (production path, harness path).

    THE TWO DOORWAYS. Every metric module can be reached two ways, and until
    this existed only one of them was ever checked:

    * The PRODUCTION path -- ``catalog.lanes_for_event``, i.e. the ``BY_EVENT``
      index plus ``Lane.matches``. The game canvas, the reports and
      ``game_metrics`` all use this and nothing else.
    * The HARNESS path -- a module's own base set (a scan for the supplier
      event name) plus ``FilterGroups.matching``, which is what
      ``FilterGroups.rows`` and therefore ``get_full_data`` are built from.
      This is the one :func:`capture` snapshots.

    They share the predicates and nothing else, so the snapshot only protects
    what anyone actually sees IF the two agree. Nothing asserted that. A
    sweep instrumented on two games called ``lanes_for_event`` 0 times and
    ``Lane.matches`` 0 times, and deleting 'shot' from ``BY_EVENT`` -- which
    zeroes every shot lane on the canvas and in every report, touching no
    predicate -- left ``compare`` reporting IDENTICAL.
    """
    from collections import defaultdict
    from hockey.derive import metric_catalog as catalog

    production: dict[str, list] = defaultdict(list)
    for event in game.events:
        for key in catalog.lanes_for_event(event):
            production[key].append(event)

    harness: dict[str, list] = {}
    for section in catalog.TREE:
        for population in section.populations:
            module = _load_module(population.module)
            # _find_groups rather than a second copy of the same scan: it is
            # how the catalog itself locates a population's FilterGroups.
            groups = catalog._find_groups(module, population.event_name)
            events = [e for e in game.events if e.name == groups.name]
            harness[population.all_lane.key] = events
            for group, lanes in population.groups:
                for lane in lanes:
                    harness[lane.key] = groups.matching(events, group, lane.item)
    return production, harness


def crosscheck_paths(game_ids: Iterable[str | int], sources: Iterable[str],
                     conn=None) -> dict[str, list]:
    """Compare the production path against the harness path, lane by lane.

    Same report shape as :func:`diff`, so :func:`print_diff` renders it. A
    disagreement means either a predicate moved or the catalog wiring broke --
    and either way the golden snapshot has stopped describing what the canvas
    and the reports compute.
    """
    report: dict[str, list] = {
        'count_changed': [], 'events_changed': [], 'removed': [],
        'added': [], 'errors_new': [], 'errors_fixed': [],
    }
    for source in sources:
        for game_id in game_ids:
            try:
                game, _ = _load(int(game_id), source, conn)
                production, harness = _lane_events_by_path(game)
            except Exception as exc:
                report['errors_new'].append(
                    (f"{source}/{game_id}/!load",
                     {'error': f"{type(exc).__name__}: {exc}"}))
                continue
            for lane_key in sorted(set(production) | set(harness)):
                a = list(production.get(lane_key, []))
                b = list(harness.get(lane_key, []))
                key = f"{source}/{game_id}/{lane_key}"
                va = {'n': len(a), 'sig': signature(a)}
                vb = {'n': len(b), 'sig': signature(b)}
                if len(a) != len(b):
                    report['count_changed'].append((key, va, vb))
                elif va['sig'] != vb['sig']:
                    report['events_changed'].append((key, va, vb))
    return report


def db_connection(args):
    """Connect for the 'database' source. Azure env by default."""
    import os
    import mysql.connector
    host = args.db_host or os.getenv("DATABASE_HOST_AZURE")
    user = args.db_user or os.getenv("DATABASE_USERNAME_AZURE")
    password = args.db_password if args.db_password is not None else os.getenv("DATABASE_PWD_AZURE")
    name = args.db_name or os.getenv("DATABASE_NAME_AZURE", "sportlogiq")
    kwargs = dict(host=host, user=user, password=password, database=name)
    ca = os.getenv("DATABASE_SSL_CA")
    if ca and host not in ("localhost", "127.0.0.1"):
        kwargs["ssl_ca"] = os.path.expanduser(ca)
    else:
        kwargs["auth_plugin"] = "mysql_native_password"
    return mysql.connector.connect(**kwargs)


def games_in_db(conn) -> set[int]:
    """Game sl_ids that actually have events, so the sweep can skip the rest."""
    cursor = conn.cursor()
    try:
        cursor.execute("""SELECT g.sl_id FROM game g
                          JOIN event e ON e.game_id = g.id
                          GROUP BY g.sl_id""")
        return {int(r[0]) for r in cursor.fetchall()}
    finally:
        cursor.close()


def default_game_ids(limit: int) -> list[int]:
    """Games present on disk with both playsequence files."""
    catalog = DataCatalog(settings.data_root_dir)
    ids: list[int] = []
    for league, season in ((17, "20252026"), (1, "20252026")):
        try:
            ids.extend(catalog.scheduled_game_ids(league, season))
        except Exception:
            continue
    root = Path(settings.data_root_dir)
    usable = [g for g in dict.fromkeys(ids)
              if (root / str(g) / "playsequence.json").exists()
              and (root / str(g) / "playsequence_compiled.json").exists()]
    return usable[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',
                        choices=('capture', 'compare', 'crosscheck', 'crosspath'))
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument('--games', type=int, default=20,
                        help='how many games to sweep (default 20)')
    parser.add_argument('--game-ids', type=int, nargs='*',
                        help='explicit game ids, overriding --games')
    parser.add_argument('--sources', nargs='*', default=list(SOURCES),
                        help=f"any of {ALL_SOURCES}")
    parser.add_argument('--db-host'); parser.add_argument('--db-user')
    parser.add_argument('--db-password'); parser.add_argument('--db-name')
    parser.add_argument('--limit', type=int, default=25,
                        help='max rows printed per diff bucket')
    args = parser.parse_args()

    conn = None
    if DATABASE_SOURCE in args.sources:
        conn = db_connection(args)

    game_ids = args.game_ids or default_game_ids(args.games)
    if conn is not None:
        # A game missing from the database would otherwise fill the report
        # with load errors that say nothing about the metrics.
        available = games_in_db(conn)
        game_ids = [g for g in game_ids if g in available]
        if not game_ids and args.game_ids:
            game_ids = [g for g in args.game_ids if g in available]
    if not game_ids:
        print("no games available in every requested source")
        return 2

    if args.command == 'crosspath':
        # No snapshot involved: this compares two ways of computing the same
        # lanes right now, so capturing one would only be slow.
        started = time.perf_counter()
        report = crosscheck_paths(game_ids, args.sources, conn)
        print(f"checked {len(game_ids)} games x {len(args.sources)} sources "
              f"in {time.perf_counter() - started:.1f}s")
        ok_ = print_diff(report, args.limit,
                         "IDENTICAL — the production path (catalog) and the "
                         "harness path (get_full_data) agree on every lane.")
        return 0 if ok_ else 1

    started = time.perf_counter()
    snapshot = capture(game_ids, args.sources, conn)
    elapsed = time.perf_counter() - started
    metrics = len(snapshot['results'])
    print(f"swept {len(game_ids)} games x {len(args.sources)} sources "
          f"-> {metrics} metric rows in {elapsed:.1f}s")

    if args.command == 'crosscheck':
        if len(args.sources) != 2:
            print("crosscheck needs exactly two --sources")
            return 2
        a, b = args.sources
        report = crosscheck(snapshot, a, b)
        for side, games in (('only in ' + a, report.pop('only_in_a')),
                            ('only in ' + b, report.pop('only_in_b'))):
            if games:
                print(f"\n{side}: {len(games)} games skipped ({', '.join(games[:6])}...)")
        print(f"\ncomparing {a}  vs  {b}")
        ok_ = print_diff(report, args.limit,
                         f"IDENTICAL — {a} and {b} agree on every metric.")
        return 0 if ok_ else 1

    if args.command == 'capture':
        args.snapshot.write_text(json.dumps(snapshot, indent=1, sort_keys=True))
        print(f"wrote {args.snapshot}")
        return 0

    if not args.snapshot.exists():
        print(f"no snapshot at {args.snapshot} -- run 'capture' first")
        return 2
    golden = json.loads(args.snapshot.read_text())
    clean = print_diff(diff(golden, snapshot), args.limit)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
