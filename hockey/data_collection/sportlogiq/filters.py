"""Shared query-parameter vocabulary for the v3 API.

The same filter parameters recur across tags: ``teamid`` appears on 14 of the
59 endpoints, ``playerid`` and ``period`` on 12 each, ``mps``/``mpsskaters`` on
8. Rather than a dataclass per endpoint, there is one :class:`QueryFilters`
covering the full vocabulary plus a per-endpoint allowlist (the ``*_FILTERS``
frozensets below) that each resource passes to
:meth:`QueryFilters.to_params`. Fields outside the allowlist are dropped, so
sending ``mps`` to an endpoint that does not accept it cannot produce a 400.

Arrays serialise PHP-style as repeated ``name[]`` keys, per the spec::

    mps[]=ES&mpsskaters[]=5v4&mps[]=PP&mpsskaters[]=4v3

Order therefore matters — ``mps`` and ``mpsskaters`` are paired by position —
so params are built as ordered lists of 2-tuples, never dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .enums import Arena, ManpowerSituation, PeriodType, Perspective, Position

Params = list[tuple[str, str]]

# Every filter field, in the order they are serialised.
ALL_FILTERS = frozenset(
    {
        "from",
        "to",
        "mps",
        "mpsskaters",
        "period",
        "periodtype",
        "arena",
        "scoredifferential",
        "playersalary",
        "opposinggoalieid",
        "position",
        "teamid",
        "playerid",
        "opposingplayerid",
        "opposingteamid",
        "woi",
    }
)

# Per-endpoint allowlists, taken from the spec. Names match the wire names.
STATS_CONTEXT_FILTERS = ALL_FILTERS - {
    "playerid",
    "opposingplayerid",
    "opposingteamid",
    "woi",
}
METRIC_VALUE_FILTERS = ALL_FILTERS
METRIC_EVENT_FILTERS = ALL_FILTERS
SHIFTS_FILTERS = frozenset(
    {
        "from",
        "to",
        "mps",
        "mpsskaters",
        "period",
        "position",
        "playerid",
        "opposingplayerid",
        "opposingteamid",
    }
)
"""Note the absence of ``teamid``: /api/v3/shifts is the one endpoint that
takes it as a scalar string rather than a ``teamid[]`` array, so it is passed
explicitly by :meth:`GamesResource.shifts` instead of through the filter block."""
GAMES_FILTERS = frozenset({"from", "to", "teamid", "playerid"})
GAME_CONTEXT_FILTERS = frozenset(
    {
        "mps",
        "mpsskaters",
        "period",
        "periodtype",
        "teamid",
        "playerid",
        "opposingteamid",
        "woi",
    }
)
EVENT_STREAM_FILTERS = frozenset({"period", "teamid", "playerid"})
"""Shared by /gameevents, /playerevents and /playershiftevents."""
GAME_HISTORY_FILTERS = frozenset({"from", "to", "teamid"})


def to_bool(value: bool) -> str:
    """The API expects lowercase JSON-style booleans, not Python's ``True``."""
    return "true" if value else "false"


def scalar(name: str, value: object | None) -> Params:
    """One optional scalar query param."""
    if value is None:
        return []
    if isinstance(value, bool):
        return [(name, to_bool(value))]
    return [(name, str(value))]


def array(name: str, values: Iterable[object] | object) -> Params:
    """Repeated ``name[]`` params.

    A bare scalar is treated as a one-element list, so ``seasonstage="regular"``
    behaves like ``seasonstage=["regular"]``. Without this, a string would be
    iterated character by character into ``seasonstage[]=r&seasonstage[]=e&...``
    and an int would raise TypeError.
    """
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        values = [values]
    return [(f"{name}[]", str(v)) for v in values]


@dataclass(slots=True)
class QueryFilters:
    """The v3 filter vocabulary, shared across metrics, games, events and shifts.

    ``mps`` and ``mpsskaters`` are positionally paired: for ES-5v4 or PP-4v3,
    pass ``mps=["ES", "PP"], mpsskaters=["5v4", "4v3"]``.

    ``scoredifferential`` and ``playersalary`` take operator-prefixed strings,
    e.g. ``[">=2"]`` or ``["<950000"]``.

    ``woi`` matches players who were *on ice* rather than those who caused the
    event.

    Not every endpoint accepts every field — see the ``*_FILTERS`` allowlists.
    """

    from_: str | None = None          # ISO 8601 UTC, inclusive
    to: str | None = None             # ISO 8601 UTC, inclusive
    mps: Sequence[ManpowerSituation] = field(default_factory=list)
    mpsskaters: Sequence[str] = field(default_factory=list)
    period: Sequence[int] = field(default_factory=list)
    periodtype: PeriodType | None = None
    arena: Sequence[Arena] = field(default_factory=list)
    scoredifferential: Sequence[str] = field(default_factory=list)
    playersalary: Sequence[str] = field(default_factory=list)
    opposinggoalieid: Sequence[str | int] = field(default_factory=list)
    position: Sequence[Position] = field(default_factory=list)
    teamid: Sequence[str | int] = field(default_factory=list)
    playerid: Sequence[str | int] = field(default_factory=list)
    opposingplayerid: Sequence[str | int] = field(default_factory=list)
    opposingteamid: Sequence[str | int] = field(default_factory=list)
    woi: bool | None = None

    #: Array fields, in serialisation order. mps/mpsskaters lead so the paired
    #: manpower filters stay adjacent and in the order the caller gave them.
    _ARRAY_FIELDS = (
        ("mps", "mps"),
        ("mpsskaters", "mpsskaters"),
        ("period", "period"),
        ("arena", "arena"),
        ("scoredifferential", "scoredifferential"),
        ("playersalary", "playersalary"),
        ("opposinggoalieid", "opposinggoalieid"),
        ("position", "position"),
        ("teamid", "teamid"),
        ("playerid", "playerid"),
        ("opposingplayerid", "opposingplayerid"),
        ("opposingteamid", "opposingteamid"),
    )

    def to_params(self, only: frozenset[str] = ALL_FILTERS) -> Params:
        """Serialise, keeping only fields in the ``only`` allowlist."""
        params: Params = []
        if "from" in only:
            params += scalar("from", self.from_)
        if "to" in only:
            params += scalar("to", self.to)

        for attr, wire in self._ARRAY_FIELDS:
            if wire in only:
                params += array(wire, getattr(self, attr))

        if "periodtype" in only:
            params += scalar("periodtype", self.periodtype)
        if "woi" in only:
            params += scalar("woi", self.woi)
        return params

    def set_fields(self) -> set[str]:
        """Wire names of the fields that actually carry a value."""
        names = set()
        for wire in ALL_FILTERS:
            attr = "from_" if wire == "from" else wire
            if getattr(self, attr) not in (None, [], (), ""):
                names.add(wire)
        return names

    def rejected(self, only: frozenset[str]) -> set[str]:
        """Fields that are set but would be dropped by ``only``.

        Useful for warning at call sites rather than silently ignoring input.
        """
        dropped = set()
        for wire in ALL_FILTERS - only:
            attr = "from_" if wire == "from" else wire
            value = getattr(self, attr)
            if value not in (None, [], (), ""):
                dropped.add(wire)
        return dropped


_SCALAR_WIRE_NAMES = frozenset({"from", "to", "periodtype", "woi"})
"""Filter fields the API takes as plain params rather than ``name[]`` arrays."""


def combine(
    explicit: dict[str, object],
    filters: QueryFilters | None,
    allow: frozenset[str],
) -> Params:
    """Merge explicit keyword filters with an optional :class:`QueryFilters`.

    Endpoints that accept only a handful of plain id/date filters expose them
    as ordinary keyword arguments — spelling out ``teamid=[1]`` beats wrapping
    it in an object. ``filters`` still works for callers reusing one built
    elsewhere; it fills in whatever was not passed explicitly.

    Raises ``ValueError`` if the same field is supplied both ways, rather than
    silently picking one.

    ``explicit`` maps wire names to values; sequences become ``name[]`` arrays,
    scalars become plain params, and empty/None values are skipped.
    """
    given = {
        name for name, value in explicit.items() if value not in (None, (), [], "")
    }

    if filters is not None:
        clash = given & filters.set_fields()
        if clash:
            raise ValueError(
                f"{', '.join(sorted(clash))} passed both as a keyword argument "
                "and on the filters object; pass it one way only."
            )

    params: Params = []
    for name, value in explicit.items():
        if value in (None, (), [], ""):
            continue
        if name in _SCALAR_WIRE_NAMES:
            params += scalar(name, value)
        else:
            params += array(name, value)

    if filters is not None:
        params += filters.to_params(allow - given)
    return params


@dataclass(slots=True)
class EventOptions:
    """Extra parameters accepted by the three ``metricevents`` endpoints.

    These are the only endpoints in the spec with ``maxcount``/``offset``
    pagination.
    """

    gameid: Sequence[str | int] = field(default_factory=list)
    perspective: Perspective | None = None   # trims the returned key set
    withvidparams: bool | None = None
    withplayers: bool | None = None
    maxcount: int | None = None              # page size
    offset: int | None = None                # page start

    def to_params(self) -> Params:
        params: Params = array("gameid", self.gameid)
        params += scalar("perspective", self.perspective)
        params += scalar("withvidparams", self.withvidparams)
        params += scalar("withplayers", self.withplayers)
        params += scalar("maxcount", self.maxcount)
        params += scalar("offset", self.offset)
        return params
