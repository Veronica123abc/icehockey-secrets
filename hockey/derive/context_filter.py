#!/usr/bin/python
"""Game-context filtering: team, period, manpower and goalie situation.

A context filter narrows a list of events by the SITUATION they happened in,
independently of what kind of event they are. It composes with the metric
filters in ``*_FILTERS`` rather than replacing them: pick the metric with
those, pick the situation with this.

It takes any iterable of :class:`~hockey.model.events.Event` -- one game or
many -- and knows nothing about any particular visual. The only thing that is
data-dependent is the team list, which :func:`options` reads off the events
themselves.

EVERYTHING IS RELATIVE TO ``event.team_id``. "Shorthanded" means the team
credited with the event was shorthanded; "Goalie out" means THAT team's goalie
was off. This matches how the metric modules treat team_id, so selecting a
team and a situation reads naturally: "Brynas, shorthanded by one".

WHERE THE VALUES COME FROM. The supplier's own fields are used wherever it
publishes one, and only the parts it does not publish are derived:

* PERIOD -- ``raw['period']`` (1, 2, 3, 4). Present on every source including
  the database. Period 4 is overtime, and carries the shootout events too.
  Falls back to ``t // 1200`` only when the field is absent.
* MANPOWER DIRECTION -- ``raw['manpower_situation']``: 'evenStrength',
  'powerPlay' or 'shortHanded'. This is authoritative.
* MANPOWER MAGNITUDE -- NOT published: the supplier's field is three-valued,
  so the 1-vs-2 split is derived from the skater counts.
* GOALIE -- ``team_goalie_on_ice_ref`` / ``opposing_team_goalie_on_ice_ref``.
  A null ref means that goalie is off the ice.

THE PULLED-GOALIE ADJUSTMENT. Skater counts include the extra attacker a
pulled goalie buys, so a raw difference misreads an empty net: 6v5 is even
strength, not a one-man advantage, and the supplier agrees -- it labels those
33 events 'evenStrength'. So magnitude is computed on skaters MINUS the extra
attacker whenever that team's goalie ref is null. Verified over 8 games: the
adjusted difference agrees in sign with the supplier's own label on 100% of
28421 classifiable uncompiled events and 99.69% of 46989 compiled ones. The
148 compiled exceptions are all cases where the supplier calls a power play
what the skaters read as shorthanded; the supplier's direction wins and only
the magnitude comes from the counts, so those stay PP1.

UNKNOWNS ARE NOT GUESSES. A dimension that cannot be determined -- no manpower
field, null skater counts, no team -- classifies as ``None`` and matches no
specific value. On the uncompiled path ~3.5% of events carry no on-ice data at
all, and those are excluded by any narrowing selection rather than being
silently folded into 'ES'.

EVENTS ARE NOT THE ONLY THING WITH A SITUATION. Time on ice has one too, and a
shift carries none of the supplier fields above -- it is an interval, not an
event. So the classification rules are exposed over plain numbers as well
(:func:`period_from_time`, :func:`manpower_from_skaters`,
:func:`goalies_from_flags`), and the selection itself is
:meth:`ContextFilter.matches_situation`, which :meth:`ContextFilter.matches`
delegates to once it has classified an event. One definition of "selected",
two ways of arriving at it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from hockey.model.events import Event

# --- Dimension names ------------------------------------------------------

TEAM = "Team"
PERIOD = "Period"
MANPOWER = "Manpower"
GOALIES = "Goalies"

DIMENSIONS = (TEAM, PERIOD, MANPOWER, GOALIES)

# --- Period ---------------------------------------------------------------

ALL = "All"
P1, P2, P3, OT = "P1", "P2", "P3", "OT"
PERIODS = (ALL, P1, P2, P3, OT)

_PERIOD_BY_NUMBER = {1: P1, 2: P2, 3: P3}
PERIOD_LENGTH = 1200

# --- Manpower -------------------------------------------------------------

ES = "ES"
SH1, SH2 = "SH1", "SH2"
PP1, PP2 = "PP1", "PP2"
MANPOWERS = (ES, SH1, SH2, PP1, PP2)

_EVEN = "evenStrength"
_POWERPLAY = "powerPlay"
_SHORTHANDED = "shortHanded"

# --- Goalies --------------------------------------------------------------

BOTH_GOALIES = "Both goalies on ice"
GOALIE_OUT = "Goalie out"
OPPONENT_GOALIE_OUT = "Opponent goalie out"
GOALIE_SITUATIONS = (BOTH_GOALIES, GOALIE_OUT, OPPONENT_GOALIE_OUT)


# --- Classifiers ----------------------------------------------------------
# Each answers "which value of this dimension does the event sit in", or None
# when the event does not carry enough to say.

def team_of(event: Event) -> int | None:
    """The team the event is credited to."""
    return event.team_id


def period_of(event: Event) -> str | None:
    """P1/P2/P3/OT. Period 4 and beyond is overtime, shootouts included."""
    number = event.get_raw("period")
    if number is None:
        # Only for a source that omits the field; every source seen carries it.
        if event.t is None:
            return None
        number = int(event.t // PERIOD_LENGTH) + 1
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    return _PERIOD_BY_NUMBER.get(number, OT if number >= 4 else None)


def period_from_time(t: float | None) -> str | None:
    """P1/P2/P3/OT from a game time, for data carrying no period field.

    A shift is an interval with no period on it, so TOI has to derive one.
    This is not an approximation: checked against the events, which do carry
    the field, ``t // 1200 + 1`` agrees with ``raw['period']`` on every one of
    the 11888 events of games 186461 and 186449, overtime included.
    """
    if t is None:
        return None
    number = int(t // PERIOD_LENGTH) + 1
    return _PERIOD_BY_NUMBER.get(number, OT if number >= 4 else None)


def _effective_skaters(skaters: int | None, goalie_off: bool) -> int | None:
    """Skaters minus the extra attacker a pulled goalie buys.

    Without this, an empty net reads as a power play: 6v5 would be +1 when it
    is really even strength.
    """
    if skaters is None:
        return None
    return skaters - 1 if goalie_off else skaters


def manpower_magnitude(event: Event) -> int | None:
    """How many skaters separate the teams, ignoring who is ahead.

    None when the counts are missing. Clamped to 2: a three-man difference is
    rare enough (8 events in 47k) that a separate bucket would be noise, and
    the caller asked for PP1/PP2 and SH1/SH2 only.
    """
    own = _effective_skaters(event.team_skaters_on_ice,
                             event.team_goalie_on_ice_ref is None)
    opp = _effective_skaters(event.opposing_team_skaters_on_ice,
                             event.opposing_team_goalie_on_ice_ref is None)
    if own is None or opp is None:
        return None
    return min(2, abs(own - opp))


def manpower_from_skaters(own: int, opposing: int, *,
                          own_goalie_on: bool, opposing_goalie_on: bool) -> str:
    """ES/PP1/PP2/SH1/SH2 from who is on the ice, relative to ``own``.

    This is the TOI path. An event carries the supplier's own
    ``manpower_situation`` and :func:`manpower_of` takes the direction from it;
    a shift carries nothing, so the direction has to be derived here too. The
    two agree in sign on 100% of 28421 uncompiled and 99.69% of 46989 compiled
    events, so a count taken from the supplier and a denominator derived here
    classify the same moments, give or take a few empty-net seconds.

    The pulled-goalie adjustment is the one :func:`manpower_magnitude` applies:
    a team with its goalie off has bought an extra attacker, not an advantage,
    so 6v5 is even strength.
    """
    difference = ((own - (0 if own_goalie_on else 1))
                  - (opposing - (0 if opposing_goalie_on else 1)))
    if difference == 0:
        return ES
    magnitude = min(2, abs(difference))
    if difference > 0:
        return PP1 if magnitude == 1 else PP2
    return SH1 if magnitude == 1 else SH2


def manpower_of(event: Event) -> str | None:
    """ES / SH1 / SH2 / PP1 / PP2.

    Direction is the supplier's ``manpower_situation``; only the magnitude is
    derived. A power play whose magnitude cannot be computed, or computes as
    zero, still counts as PP1 -- the supplier said it was a power play, and
    dropping it would lose the event entirely.
    """
    situation = event.get_raw("manpower_situation")
    if situation == _EVEN:
        return ES
    if situation not in (_POWERPLAY, _SHORTHANDED):
        return None
    magnitude = manpower_magnitude(event) or 1
    magnitude = max(1, magnitude)
    if situation == _POWERPLAY:
        return PP1 if magnitude == 1 else PP2
    return SH1 if magnitude == 1 else SH2


def goalies_of(event: Event) -> str | None:
    """Which goalies were on the ice.

    A null goalie ref means that goalie is off. Verified: every event with six
    own skaters has a null own-goalie ref and vice versa. Events carrying no
    on-ice data at all (null skater counts) are unknown rather than "out".
    """
    if event.team_skaters_on_ice is None and event.opposing_team_skaters_on_ice is None:
        return None
    own_off = event.team_goalie_on_ice_ref is None
    opp_off = event.opposing_team_goalie_on_ice_ref is None
    # Both nets empty at once does occur -- once in three games -- but there
    # are three values here, not four, so it folds into "Goalie out". That is
    # true of this team; it is simply not the whole story.
    if own_off:
        return GOALIE_OUT
    if opp_off:
        return OPPONENT_GOALIE_OUT
    return BOTH_GOALIES


def goalies_from_flags(own_goalie_on: bool, opposing_goalie_on: bool) -> str:
    """The goalie situation from who is on the ice, relative to ``own``.

    The TOI counterpart of :func:`goalies_of`, folding both-nets-empty into
    "Goalie out" the same way it does.
    """
    if not own_goalie_on:
        return GOALIE_OUT
    if not opposing_goalie_on:
        return OPPONENT_GOALIE_OUT
    return BOTH_GOALIES


CLASSIFIERS = {
    TEAM: team_of,
    PERIOD: period_of,
    MANPOWER: manpower_of,
    GOALIES: goalies_of,
}


# --- The selection --------------------------------------------------------

@dataclass(frozen=True)
class ContextFilter:
    """One selection per dimension. Several values in a dimension mean OR.

    Defaults are the ones the UI opens on: every team, every period, even
    strength, both goalies on the ice.

    ``teams=None`` means every team, which is not the same as an empty set --
    an empty set matches nothing, and is how "deselect everything" behaves.
    """
    teams: frozenset[int] | None = None
    periods: frozenset[str] = frozenset({ALL})
    manpower: frozenset[str] = frozenset({ES})
    goalies: frozenset[str] = frozenset({BOTH_GOALIES})

    # -- construction ------------------------------------------------------

    @classmethod
    def default(cls) -> "ContextFilter":
        return cls()

    def with_values(self, dimension: str, values: Iterable | None) -> "ContextFilter":
        """A copy with one dimension replaced. ``None`` clears a team filter."""
        if dimension == TEAM:
            return replace(self, teams=None if values is None
                           else frozenset(int(v) for v in values))
        if dimension == PERIOD:
            return replace(self, periods=frozenset(values))
        if dimension == MANPOWER:
            return replace(self, manpower=frozenset(values))
        if dimension == GOALIES:
            return replace(self, goalies=frozenset(values))
        raise KeyError(f"unknown dimension {dimension!r}; expected one of {DIMENSIONS}")

    # -- predicates --------------------------------------------------------

    @property
    def all_periods(self) -> bool:
        return ALL in self.periods or not self.periods

    def matches_situation(self, *, team_id: int | None = None,
                          period: str | None = None,
                          manpower: str | None = None,
                          goalies: str | None = None) -> bool:
        """Whether a SITUATION is selected, however it came to be classified.

        This is the selection rule with the classifying already done. An event
        arrives through :meth:`matches`; a stretch of ice time, which is not an
        event and carries no supplier fields, classifies itself and arrives
        here. Both therefore honour one definition of "selected".

        A dimension given as None matches nothing, which is how an
        unclassifiable event or slice drops out instead of being assumed.
        """
        if self.teams is not None and team_id not in self.teams:
            return False
        if not self.all_periods and period not in self.periods:
            return False
        if manpower not in self.manpower:
            return False
        if goalies not in self.goalies:
            return False
        return True

    def matches(self, event: Event) -> bool:
        """Whether an event happened in the selected context."""
        return self.matches_situation(
            team_id=team_of(event),
            period=period_of(event),
            manpower=manpower_of(event),
            goalies=goalies_of(event))

    # -- reporting ---------------------------------------------------------

    def is_default(self) -> bool:
        return self == ContextFilter()

    def describe(self, team_labels: dict[int, str] | None = None) -> list[str]:
        """Short chips naming the selection, for a header or a report."""
        labels = team_labels or {}
        out = []
        if self.teams is None:
            out.append("All teams")
        else:
            out.append(", ".join(str(labels.get(t, t)) for t in sorted(self.teams))
                       or "No team")
        out.append("All periods" if self.all_periods
                   else ", ".join(p for p in PERIODS if p in self.periods))
        out.append(", ".join(m for m in MANPOWERS if m in self.manpower) or "No manpower")
        out.append(", ".join(g for g in GOALIE_SITUATIONS if g in self.goalies)
                   or "No goalie situation")
        return out


DEFAULT = ContextFilter()


# --- Applying it ----------------------------------------------------------

def apply(events: Iterable[Event], context: ContextFilter | None = None) -> list[Event]:
    """The events that happened in the selected context."""
    context = context or DEFAULT
    return [e for e in events if context.matches(e)]


def teams_in(events: Iterable[Event]) -> list[int]:
    """Team ids occurring in the events, sorted. Works across several games."""
    return sorted({e.team_id for e in events if e.team_id is not None})


def options(events: Iterable[Event]) -> dict[str, list]:
    """Selectable values per dimension, with teams read off the events.

    The static dimensions are returned whole rather than narrowed to what
    occurs, so a UI built from this keeps a stable shape -- a game with no
    overtime still shows OT, greyed out by its own zero count.
    """
    return {
        TEAM: teams_in(events),
        PERIOD: list(PERIODS),
        MANPOWER: list(MANPOWERS),
        GOALIES: list(GOALIE_SITUATIONS),
    }


def counts(events: Iterable[Event]) -> dict[str, dict]:
    """How many events sit in each value of each dimension.

    Independent per dimension -- the numbers are not narrowed by the current
    selection, so they say what is available, not what is showing. ``None``
    counts the events a dimension could not classify.
    """
    events = list(events)
    out: dict[str, dict] = {}
    for dimension, classify in CLASSIFIERS.items():
        tally: dict = {}
        for e in events:
            key = classify(e)
            tally[key] = tally.get(key, 0) + 1
        out[dimension] = tally
    return out


if __name__ == "__main__":
    from pathlib import Path
    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
    events = []
    labels: dict[int, str] = {}
    for game_id in (186461, 191848):
        game = build_game(RawGame(game_id=game_id, root_dir=settings.data_root_dir,
                                  playsequence_source="playsequence_compiled"))
        events += game.events
        labels[game.info.home_team.id] = game.info.home_team.name
        labels[game.info.away_team.id] = game.info.away_team.name

    print(f"{len(events)} events from {len({e.game_id for e in events})} games\n")
    for dimension, tally in counts(events).items():
        pretty = {k: v for k, v in sorted(tally.items(), key=lambda kv: -kv[1])}
        print(f"  {dimension:9s} {pretty}")

    print(f"\n  teams in the list: {teams_in(events)} -> "
          f"{[labels.get(t, t) for t in teams_in(events)]}")

    print(f"\n  default selection: {' · '.join(DEFAULT.describe(labels))}")
    print(f"     {len(apply(events, DEFAULT)):>6} of {len(events)} events")

    pp = DEFAULT.with_values(MANPOWER, [PP1, PP2])
    print(f"\n  power play: {' · '.join(pp.describe(labels))}")
    print(f"     {len(apply(events, pp)):>6} events")

    third = DEFAULT.with_values(PERIOD, [P3]).with_values(GOALIES, [OPPONENT_GOALIE_OUT])
    print(f"\n  P3, opponent net empty: {' · '.join(third.describe(labels))}")
    print(f"     {len(apply(events, third)):>6} events")

    one_team = DEFAULT.with_values(TEAM, teams_in(events)[:1])
    print(f"\n  one team: {' · '.join(one_team.describe(labels))}")
    print(f"     {len(apply(events, one_team)):>6} events")
