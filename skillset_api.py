"""The skill-set builder: defining a skill set's counts by clicking the metric tree.

WHAT THIS SERVES. One page, ``/skillsets/builder``. Sections down the left;
picking one draws its populations on the canvas, and picking a population
expands it into its tree -- population, groups, leaves -- the shape the
catalog already has (``hockey/derive/metric_catalog.py``). Ticking leaves and
pressing "Add to skillset" turns the selection into one COUNT of a skill-set
config (``hockey/predict/skillset.py``).

AND/OR IS THE TREE'S SHAPE, NOT A SEPARATE BUILDER. A count is a list of
lanes of ONE population, read the way :class:`~hockey.metrics.on_ice.Column`
reads it: leaves on different branches (groups) are ANDed, leaves on the same
branch are ORed. "Screened shots that were successful" is two leaves on two
branches. The page spells the rule out in words before it is added, because
that reading is the part nobody can see from the ticks alone.

THE FORMULA. Below the tree, counts become INPUTS -- a per-20 sum of counts
or a ratio of two -- each with a weight, plus an intercept. Weights start at
1 and the intercept at 0: a skill set of our own has no fitted weights until
someone fits them. The draft carries the supplier's context (even strength in
regulation, every goalie situation) and the regular season, written out
rather than left to ``read_skillset``'s defaults, so the JSON says what it
means and loads as it is.

NOT SAVED YET. The draft lives in the page (and the browser's local
storage); nothing is written to ``hockey/predict/skillsets/``. The page shows
the JSON to copy.
"""
from __future__ import annotations

from flask import Blueprint, render_template

skillset_bp = Blueprint("skillsets", __name__)


def _tree() -> list[dict]:
    """The catalog as plain data: section -> population -> group -> leaves."""
    from hockey.derive import lane_docs
    from hockey.derive import metric_catalog as catalog

    def leaf(lane):
        return {"key": lane.key, "item": lane.item, "description": lane.description}

    return [{
        "section": section.label,
        "populations": [{
            "label": pop.label,
            "description": lane_docs.for_population(pop.label),
            "all": leaf(pop.all_lane),
            "groups": [{"group": group,
                        "description": lane_docs.for_group(pop.label, group),
                        "items": [leaf(lane) for lane in lanes]}
                       for group, lanes in pop.groups],
        } for pop in section.populations],
    } for section in catalog.TREE]


def _supplier_context() -> dict[str, list[str]]:
    """Even strength as the supplier counts it, as a config's "context".

    Even manpower whatever the goalies are doing, and regulation only: the
    supplier's even strength leaves 3-on-3 overtime out (see skating.json).
    Built from context_filter's constants so it cannot drift from them.
    """
    from hockey.derive import context_filter as ctx
    return {ctx.MANPOWER: [ctx.ES],
            ctx.PERIOD: [ctx.P1, ctx.P2, ctx.P3],
            ctx.GOALIES: list(ctx.GOALIE_SITUATIONS)}


@skillset_bp.route("/skillsets/builder")
def builder():
    from hockey.metrics.on_ice import AGAINST, BOTH, CREDITED, FOR, REGULAR

    sides = [(CREDITED, "Credited", "the player's own events"),
             (FOR, "For", "his team's, while he is on the ice"),
             (AGAINST, "Against", "the opponents', while he is on the ice"),
             (BOTH, "Both", "either team's, while he is on the ice")]
    return render_template("skillset_builder.html", tree=_tree(), sides=sides,
                           default_side=CREDITED, context=_supplier_context(),
                           stage=REGULAR)
