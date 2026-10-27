#!/usr/bin/python
"""The supplier's "Skating" score for offensive forwards, recomputed from our lanes.

WHAT IT IS. In the portal's Player Analysis, "Compare offensive forwards" shows
a Skating value per player. It is skill metric set 37 of archetype 5
(Offensive Forwards), defined by
``GET /api/0.2/primarypositions/F/archetypeswithskillmetricsets``, and it is
NOT a percentile and NOT tracking data: it is a fixed linear combination of
seven per-player event metrics, all even strength, regular season::

    skating = INTERCEPT + sum(WEIGHTS[name] * value[name])

The intercept and weights were recovered by least squares on the portal's own
inputs and outputs for 19 Rögle forwards, SHL 2026/27, and fit exactly
(residual ~1e-14), so they are the supplier's formula rather than an estimate
of it -- for that league and season. Another league or season may carry other
weights; re-derive them the same way before trusting a number there.

The weights are per RAW unit, so they cannot be compared with each other: a
rate (0..1) and a count per 20 minutes live on different scales.

INPUTS, AND WHERE EACH COMES FROM. Credited to the player who made the event
(``CREDITED``), even strength in regulation, over the player's even-strength
minutes in regulation (:data:`CONTEXT`):

    pdp_per20          Possession Driving Plays / 20       -- see below
    ce_per20           Controlled entries · Successful / 20
    ce_play_after      Controlled entries · With Play After  /  · Successful
    oz_dekes_per20     Puck Protections · deke + OZ + Successful / 20
    oz_deke_success    Puck Protections · deke + OZ + Successful  /  deke + OZ
    oz_lprs_per20      LPRs · OZ + Successful + Is Not Faceoff / 20
    ce_scoring_chance  Controlled entries · With Slot Shot  /  · Successful

Each was checked against the portal's per-player value for nine of those
forwards: the dekes and deke rate match all nine, the entry metrics seven or
eight of nine (the misses are one entry, and ice time that differs by a
fraction of a minute), and the LPR count matches once faceoff recoveries are
excluded -- which is why ``LPRs · Is Not Faceoff`` exists. The last input has
weight exactly 0: the portal lists it but the score ignores it.

POSSESSION DRIVING PLAYS. The supplier's glossary (help.teamworks.com,
"Possession Driving Plays") lists five parts: controlled entries, redline
carries, controlled exits, completed north-bound and east-west passes from the
NZ, and completed outlet and stretch passes from the DZ. In lanes, as summed
by :data:`PDP_COLUMNS`:

    Controlled entries · Successful
    Controlled exits · Successful + Carry         exits by PASS are not here:
    Carries · NZ                                  they are the DZ outlet and
    Passes · Successful + NZ + North / East-West  stretch passes below, so
    Passes · Successful + NZ + Untyped + Entry    adding them would count the
    Passes · Successful + DZ + Outlet / Stretch   same play twice

Each pass type includes its off-the-boards and entry spellings ('ozentry',
'ozentrystretch'), because the Type lanes match the unpacked base type. Over
the nine forwards this reproduces the portal's PDP per 20 to within 0.01 for
eight and 0.12 for Joel Kellman (1881), overtime excluded as below. Leaving out the exits-by-pass is what the fit demands: counting every
exit overshoots the two smallest samples (12 PDPs each) before a single pass
is added.

NO OVERTIME. The supplier's "even strength" stops at the end of the third
period: 3-on-3 overtime is left out of both the events and the minutes.
Counting it put Charles Hudon (893) at 0.476 against the portal's 0.404 --
three extra entries, all with a play after and a slot shot, in 3.3 minutes.
Without it, 25 forwards of Rögle and Djurgården, SHL 2026/27, match the
portal to a mean of 0.0006 (0.008 with overtime).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import hockey.derive.context_filter as ctx
from hockey.metrics.on_ice import (CREDITED, Column, ColumnSet, EVEN_STRENGTH,
                                   REGULAR, open_connection, player_rows)

#: Recovered from SHL 2026/27 (league 13, season id 13), archetype 5, set 37.
INTERCEPT = -0.329061
WEIGHTS: dict[str, float] = {
    "pdp_per20":         0.0171393,
    "ce_per20":          0.0451062,
    "ce_play_after":     0.349766,
    "oz_dekes_per20":    0.0892796,
    "oz_deke_success":   0.0874415,
    "oz_lprs_per20":     0.0198566,
    "ce_scoring_chance": 0.0,
}

#: Even strength in periods 1-3: the supplier leaves overtime out.
CONTEXT = EVEN_STRENGTH.with_values(ctx.PERIOD, [ctx.P1, ctx.P2, ctx.P3])

# Totals counted per player. Lanes in one column are ANDed across groups.
_CE_OK = Column("CE ok", "Controlled entries · Successful", CREDITED, rate=False)
_CE_PLAY = Column("CE play after", ("Controlled entries · Successful",
                                    "Controlled entries · With Play After"),
                  CREDITED, rate=False)
_CE_SLOT = Column("CE slot shot", ("Controlled entries · Successful",
                                   "Controlled entries · With Slot Shot"),
                  CREDITED, rate=False)
_DEKES = Column("OZ dekes", ("Puck Protections · deke", "Puck Protections · OZ"),
                CREDITED, rate=False)
_DEKES_OK = Column("OZ dekes ok", ("Puck Protections · deke", "Puck Protections · OZ",
                                   "Puck Protections · Successful"),
                   CREDITED, rate=False)
_LPRS_OK = Column("OZ LPRs ok", ("LPRs · OZ", "LPRs · Successful",
                                 "LPRs · Is Not Faceoff"),
                  CREDITED, rate=False)
#: Possession Driving Plays: five disjoint columns, summed. Disjoint because
#: an event has one name, and the two NZ pass columns differ in their Type.
PDP_COLUMNS = (
    _CE_OK,
    Column("CX carry", ("Controlled exits · Successful", "Controlled exits · Carry"),
           CREDITED, rate=False),
    Column("NZ carries", "Carries · NZ", CREDITED, rate=False),
    Column("NZ passes", ("Passes · Successful", "Passes · NZ",
                         "Passes · North", "Passes · East-West"),
           CREDITED, rate=False),
    Column("NZ entry passes", ("Passes · Successful", "Passes · NZ",
                               "Passes · Untyped", "Passes · Entry Pass"),
           CREDITED, rate=False),
    Column("DZ passes", ("Passes · Successful", "Passes · DZ",
                         "Passes · Outlet", "Passes · Stretch"),
           CREDITED, rate=False),
)
COLUMNS = ColumnSet((_CE_PLAY, _CE_SLOT, _DEKES, _DEKES_OK, _LPRS_OK, *PDP_COLUMNS))


@dataclass
class SkatingRow:
    """One player: the sample, the seven inputs, and the score."""
    player_id: int
    name: str
    minutes: float                      # even-strength minutes
    inputs: dict[str, float] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return INTERCEPT + sum(WEIGHTS[k] * v for k, v in self.inputs.items())


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def skating(conn, players: Iterable, league: int, season: str, *,
            stage: str | None = REGULAR) -> tuple[list[SkatingRow], list[str]]:
    """Skating for ``players`` in one league season: ``(rows, unanswered)``.

    ``players`` are ids, names or anything with a ``player_id``, as for
    :func:`hockey.metrics.on_ice.player_rows`.
    """
    rows, missing = player_rows(conn, players, league, season, columns=COLUMNS,
                                context=CONTEXT, stage=stage)
    out = []
    for row in rows:
        total = {c.heading: row.totals.get(c.key, 0.0) for c in COLUMNS}
        per20 = lambda n: n / row.minutes * 20 if row.minutes else 0.0
        out.append(SkatingRow(row.player_id, row.name, row.minutes, {
            "pdp_per20":         per20(sum(total[c.heading] for c in PDP_COLUMNS)),
            "ce_per20":          per20(total[_CE_OK.heading]),
            "ce_play_after":     _ratio(total[_CE_PLAY.heading], total[_CE_OK.heading]),
            "oz_dekes_per20":    per20(total[_DEKES_OK.heading]),
            "oz_deke_success":   _ratio(total[_DEKES_OK.heading], total[_DEKES.heading]),
            "oz_lprs_per20":     per20(total[_LPRS_OK.heading]),
            "ce_scoring_chance": _ratio(total[_CE_SLOT.heading], total[_CE_OK.heading]),
        }))
    return out, missing


if __name__ == "__main__":
    # The portal's PDP and Skating for nine Rögle forwards, SHL 2026/27, read
    # on 2026-10-25 -- the check that this file reproduces the supplier. PDP is
    # computed here, so it is compared rather than fed in.
    PORTAL = {   # player: (PDP per 20, Skating)
        375: (10.082, 0.2650), 1101: (10.477, 0.4871), 1625: (9.448, 0.4632),
        1881: (10.452, 0.4312), 9878: (13.793, 0.4485), 9932: (7.424, 0.3818),
        10918: (12.393, 0.4395), 12219: (10.025, 0.5253), 16885: (8.249, 0.3743),
    }
    conn = open_connection()
    try:
        rows, missing = skating(conn, PORTAL, 13, "20262027")
    finally:
        conn.close()
    print(f"{'player':<24}{'ES min':>8}{'PDP/20':>8}{'portal':>8}"
          f"{'Skating':>9}{'portal':>8}{'diff':>8}")
    for row in rows:
        pdp, portal = PORTAL[row.player_id]
        print(f"{row.name:<24}{row.minutes:8.1f}{row.inputs['pdp_per20']:8.2f}"
              f"{pdp:8.2f}{row.score:9.3f}{portal:8.3f}{row.score - portal:8.3f}")
    if missing:
        print("unanswered:", missing)
