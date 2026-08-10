"""Endpoints tagged ``Metrics`` in the v3 spec — nine in total.

They fall into three groups:

* **definitions** — what metrics exist (report defs, collection topics, topic
  metric defs, stats context)
* **values** — aggregated numbers for a topic
* **events** — the individual events behind a single metric

The value and event endpoints each exist in two forms: a path-parameterised one
under ``/leagues/{leagueId}/...`` keyed by a ``collectionType`` enum, and a flat
query one under ``/metrics/setcollections/...`` keyed by a collection *name*.
Both are exposed; the flat form reaches collections the enum cannot name.
Verified against the API: ``collection_type="advancedStats"`` and
``metricsetcollection="newStatisticsPage"`` are the same collection.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterator, Sequence

from .._transport import Resource
from ..enums import (
    AggregationType,
    AverageGranularity,
    CollectionScope,
    CollectionType,
    GameReportName,
    LeagueReportName,
    PathSeasonStage,
    SeasonStage,
)
from ..filters import (
    METRIC_EVENT_FILTERS,
    METRIC_VALUE_FILTERS,
    STATS_CONTEXT_FILTERS,
    EventOptions,
    Params,
    QueryFilters,
    array,
    scalar,
)


def extract_events(payload: Any) -> list[Any]:
    """Pull the event rows out of a metricevents envelope.

    The envelope is ``{"events": [...], "leagueId": ..., "topicMetricKey": ...,
    "vidParams": ..., "playerDetails": ..., "perspective": ...}``.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        events = payload.get("events")
        if isinstance(events, list):
            return events
    return []


def _value_params(
    aggregationtype: AggregationType,
    averagegranularity: AverageGranularity | None,
    groupings: Sequence[str],
    live: bool,
) -> Params:
    params: Params = [("aggregationtype", aggregationtype)]
    params += scalar("averagegranularity", averagegranularity)
    params += array("groupings", groupings)
    if live:
        params += scalar("live", True)
    return params


class MetricsResource(Resource):
    """``api.metrics`` — metric definitions, aggregated values, and events."""

    # -- definitions -------------------------------------------------------

    def stats_context(
        self,
        seasonid: str | int,
        seasonstage: SeasonStage,
        leagueid: str | int,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/context/stats — context for building metric filters.

        Accepts only part of the filter vocabulary; ``playerid``,
        ``opposingplayerid``, ``opposingteamid`` and ``woi`` are dropped.
        """
        params: Params = [
            ("seasonid", str(seasonid)),
            ("seasonstage", seasonstage),
            ("leagueid", str(leagueid)),
        ]
        if filters:
            params += filters.to_params(STATS_CONTEXT_FILTERS)
        return self._t.get("/api/v3/context/stats", params)

    def game_report_defs(self, game_id: str | int, report: GameReportName) -> Any:
        """GET /api/v3/games/{gameId}/reportmetricdefs/{reportName}"""
        return self._t.get(f"/api/v3/games/{game_id}/reportmetricdefs/{report}")

    def league_report_defs(
        self, league_id: str | int, season_id: str | int, report: LeagueReportName
    ) -> Any:
        """GET /api/v3/leagues/{leagueId}/season/{seasonId}/reportmetricdefs/{reportName}

        Note the singular ``season`` in this path — the other league endpoints
        use ``seasons``. That asymmetry is in the spec, not a typo here.
        """
        return self._t.get(
            f"/api/v3/leagues/{league_id}/season/{season_id}"
            f"/reportmetricdefs/{report}"
        )

    def topics(
        self,
        league_id: str | int,
        season_id: str | int,
        collection_type: CollectionType,
        collection_scope: CollectionScope,
    ) -> Any:
        """GET .../metricsetcollections/{type}/{scope}/topics — hockey only."""
        return self._t.get(
            f"/api/v3/leagues/{league_id}/seasons/{season_id}"
            f"/metricsetcollections/{collection_type}/{collection_scope}/topics"
        )

    def topic_metrics(
        self,
        league_id: str | int,
        season_id: str | int,
        collection_type: CollectionType,
        collection_scope: CollectionScope,
        topic_id: str | int,
    ) -> Any:
        """GET .../metricsetcollections/{type}/{scope}/topics/{topicId}

        The metric definitions in a topic — use this to discover the ``metric``
        names accepted by the event endpoints.
        """
        return self._t.get(
            f"/api/v3/leagues/{league_id}/seasons/{season_id}"
            f"/metricsetcollections/{collection_type}/{collection_scope}"
            f"/topics/{topic_id}"
        )

    # -- values ------------------------------------------------------------

    def topic_values(
        self,
        league_id: str | int,
        season_id: str | int,
        season_stage: PathSeasonStage,
        collection_type: CollectionType,
        collection_scope: CollectionScope,
        topic_id: str | int,
        *,
        aggregationtype: AggregationType,
        averagegranularity: AverageGranularity | None = None,
        groupings: Sequence[str] = (),
        live: bool = False,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET .../stages/{stage}/metricsetcollections/{type}/{scope}/topics/{id}/metricvalues"""
        params = _value_params(aggregationtype, averagegranularity, groupings, live)
        if filters:
            params += filters.to_params(METRIC_VALUE_FILTERS)
        return self._t.get(
            f"/api/v3/leagues/{league_id}/seasons/{season_id}"
            f"/stages/{season_stage}"
            f"/metricsetcollections/{collection_type}/{collection_scope}"
            f"/topics/{topic_id}/metricvalues",
            params,
        )

    def collection_topic_values(
        self,
        *,
        seasonid: str | int,
        seasonstage: SeasonStage,
        leagueid: str | int,
        metricsetcollection: str,
        scope: CollectionScope,
        topicid: str | int,
        aggregationtype: AggregationType,
        averagegranularity: AverageGranularity | None = None,
        groupings: Sequence[str] = (),
        live: bool = False,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/metrics/setcollections/topicvalues

        Flat-query equivalent of :meth:`topic_values`, keyed by collection name
        (``newStatisticsPage``, ``statisticsPage``, ``pptMetrics``, ...).
        """
        params: Params = [
            ("seasonid", str(seasonid)),
            ("seasonstage", seasonstage),
            ("leagueid", str(leagueid)),
            ("metricsetcollection", metricsetcollection),
            ("scope", scope),
            ("topicid", str(topicid)),
        ]
        params += _value_params(aggregationtype, averagegranularity, groupings, live)
        if filters:
            params += filters.to_params(METRIC_VALUE_FILTERS)
        return self._t.get("/api/v3/metrics/setcollections/topicvalues", params)

    # -- events ------------------------------------------------------------

    def topic_metric_events(
        self,
        league_id: str | int,
        season_id: str | int,
        season_stage: PathSeasonStage,
        collection_type: CollectionType,
        collection_scope: CollectionScope,
        topic_id: str | int,
        *,
        metric: str,
        filters: QueryFilters | None = None,
        options: EventOptions | None = None,
    ) -> Any:
        """GET .../topics/{topicId}/metricevents — the events behind one metric."""
        params: Params = [("metric", metric)]
        if filters:
            params += filters.to_params(METRIC_EVENT_FILTERS)
        if options:
            params += options.to_params()
        return self._t.get(
            f"/api/v3/leagues/{league_id}/seasons/{season_id}"
            f"/stages/{season_stage}"
            f"/metricsetcollections/{collection_type}/{collection_scope}"
            f"/topics/{topic_id}/metricevents",
            params,
        )

    def collection_metric_events(
        self,
        *,
        seasonid: str | int,
        seasonstage: SeasonStage,
        leagueid: str | int,
        metricsetcollection: str,
        scope: CollectionScope,
        topicid: str | int,
        metric: str,
        filters: QueryFilters | None = None,
        options: EventOptions | None = None,
    ) -> Any:
        """GET /api/v3/metrics/setcollections/metricevents

        Flat-query equivalent of :meth:`topic_metric_events`.
        """
        params: Params = [
            ("seasonid", str(seasonid)),
            ("seasonstage", seasonstage),
            ("leagueid", str(leagueid)),
            ("metricsetcollection", metricsetcollection),
            ("scope", scope),
            ("topicid", str(topicid)),
            ("metric", metric),
        ]
        if filters:
            params += filters.to_params(METRIC_EVENT_FILTERS)
        if options:
            params += options.to_params()
        return self._t.get("/api/v3/metrics/setcollections/metricevents", params)

    def report_metric_events(
        self,
        *,
        seasonid: str | int,
        seasonstage: SeasonStage,
        leagueid: str | int,
        reportmetricid: str | int,
        scope: CollectionScope,
        filters: QueryFilters | None = None,
        options: EventOptions | None = None,
    ) -> Any:
        """GET /api/v3/metrics/reports/metricevents

        Valid ids are the ``metricSets[].metrics[].id`` values from
        :meth:`league_report_defs` — and only those flagged ``"playable": true``.
        Non-playable metrics (e.g. "Games Played") return HTTP 500 rather than a
        clean error. Match ``scope`` to the metric set: the ``g``-prefixed sets
        (``gTradStats``) are goalie scope.
        """
        params: Params = [
            ("seasonid", str(seasonid)),
            ("seasonstage", seasonstage),
            ("leagueid", str(leagueid)),
            ("reportmetricid", str(reportmetricid)),
            ("scope", scope),
        ]
        if filters:
            params += filters.to_params(METRIC_EVENT_FILTERS)
        if options:
            params += options.to_params()
        return self._t.get("/api/v3/metrics/reports/metricevents", params)

    # -- convenience -------------------------------------------------------

    def iter_collection_metric_events(
        self, page_size: int = 1000, **kwargs: Any
    ) -> Iterator[Any]:
        """Page through :meth:`collection_metric_events`, yielding each envelope.

        The envelope carries no total count, so paging stops when a page returns
        fewer than ``page_size`` events.
        """
        template: EventOptions = kwargs.pop("options", None) or EventOptions()
        offset = template.offset or 0
        while True:
            options = replace(template, maxcount=page_size, offset=offset)
            payload = self.collection_metric_events(options=options, **kwargs)
            rows = extract_events(payload)
            if not rows:
                return
            yield payload
            if len(rows) < page_size:
                return
            offset += len(rows)
