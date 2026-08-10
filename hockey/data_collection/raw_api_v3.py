"""Deprecated shim — use :mod:`hockey.data_collection.sportlogiq` instead.

This module was the single-file first version of the v3 client. It has been
split into a package so the remaining ~50 endpoints can be added without one
file growing unbounded:

* ``sportlogiq/_transport.py`` — session, login, retries
* ``sportlogiq/filters.py``   — the shared query vocabulary
* ``sportlogiq/enums.py``     — Literal aliases from the spec
* ``sportlogiq/resources/``   — one module per endpoint group

Migration::

    # before
    from hockey.data_collection.raw_api_v3 import RawApiV3, MetricFilters
    api = RawApiV3()
    api.collection_topics(1, 12, "advancedStats", "team")

    # after
    from hockey.data_collection.sportlogiq import SportlogiqV3, QueryFilters
    api = SportlogiqV3()
    api.metrics.topics(1, 12, "advancedStats", "team")

``MetricFilters`` is re-exported as an alias of ``QueryFilters``: the filter
block is not metrics-specific — ``/api/v3/shifts`` and several game/player
endpoints use the same parameters.
"""

from __future__ import annotations

import warnings

from .sportlogiq import (
    EventOptions,
    Params,
    QueryFilters,
    SportlogiqError,
    SportlogiqV3,
    extract_events,
)
from .sportlogiq.enums import (  # noqa: F401  (re-exported for compatibility)
    AggregationType,
    Arena,
    AverageGranularity,
    CollectionScope,
    CollectionType,
    GameReportName,
    LeagueReportName,
    ManpowerSituation,
    PathSeasonStage,
    PeriodType,
    Position,
    SeasonStage,
)

warnings.warn(
    "hockey.data_collection.raw_api_v3 is deprecated; "
    "import from hockey.data_collection.sportlogiq instead.",
    DeprecationWarning,
    stacklevel=2,
)

#: The filter block is shared API-wide, not metrics-only.
MetricFilters = QueryFilters


class RawApiV3(SportlogiqV3):
    """Old flat interface, forwarding to ``api.metrics``.

    Kept so existing scripts keep working; new code should use
    :class:`~hockey.data_collection.sportlogiq.SportlogiqV3`.
    """

    def stats_context(self, *args, **kwargs):
        return self.metrics.stats_context(*args, **kwargs)

    def game_report_metric_defs(self, *args, **kwargs):
        return self.metrics.game_report_defs(*args, **kwargs)

    def league_report_metric_defs(self, *args, **kwargs):
        return self.metrics.league_report_defs(*args, **kwargs)

    def collection_topics(self, *args, **kwargs):
        return self.metrics.topics(*args, **kwargs)

    def collection_topic_metrics(self, *args, **kwargs):
        return self.metrics.topic_metrics(*args, **kwargs)

    def collection_topic_values(self, *args, **kwargs):
        return self.metrics.topic_values(*args, **kwargs)

    def topic_values(self, *args, **kwargs):
        return self.metrics.collection_topic_values(*args, **kwargs)

    def collection_topic_metric_events(self, *args, **kwargs):
        return self.metrics.topic_metric_events(*args, **kwargs)

    def metric_events(self, *args, **kwargs):
        return self.metrics.collection_metric_events(*args, **kwargs)

    def report_metric_events(self, *args, **kwargs):
        return self.metrics.report_metric_events(*args, **kwargs)

    def iter_metric_events(self, *args, **kwargs):
        return self.metrics.iter_collection_metric_events(*args, **kwargs)


__all__ = [
    "RawApiV3",
    "SportlogiqV3",
    "SportlogiqError",
    "MetricFilters",
    "QueryFilters",
    "EventOptions",
    "Params",
    "extract_events",
]
