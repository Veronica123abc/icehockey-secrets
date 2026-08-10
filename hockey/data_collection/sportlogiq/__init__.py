"""Client for the Sportlogiq v3 API (``https://app.sportlogiq.com/api/v3``).

Built against the OpenAPI 3.1.1 spec in ``.dev-notes/openapi.json``.

Endpoints are grouped into resources hanging off one client, all sharing a
single authenticated session::

    from hockey.data_collection.sportlogiq import SportlogiqV3, QueryFilters

    api = SportlogiqV3()
    topics = api.metrics.topics(league_id=1, season_id=12,
                                collection_type="advancedStats",
                                collection_scope="team")
    values = api.metrics.topic_values(
        1, 12, "regular", "advancedStats", "team", topic_id="1",
        aggregationtype="sum",
        filters=QueryFilters(mps=["ES"], mpsskaters=["5v5"], teamid=[322]),
    )

Anything not yet wrapped is reachable through the transport::

    api.get("/api/v3/teams", [("leagueid", "1")])

This supersedes ``hockey/data_collection/sportlogiq_api_v3.py``. The older
``sportlogiq_api.py`` targets a different API entirely (``api.sportlogiq.com``
v1) and is unaffected.
"""

from __future__ import annotations

from typing import Any

from ._transport import Resource, SportlogiqError, Transport
from .enums import (
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
    Perspective,
    Position,
    SeasonStage,
)
from .enums import BoxscoreMode, EventMode
from .filters import EventOptions, Params, QueryFilters
from .resources import (
    EventsResource,
    GamesResource,
    MetricsResource,
    PlayersResource,
    TeamsResource,
    extract_events,
    extract_player_events,
)


class SportlogiqV3:
    """Entry point. Resources are attributes: ``api.metrics.topics(...)``."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.transport = Transport(
            username, password, timeout=timeout, max_retries=max_retries
        )
        self.metrics = MetricsResource(self.transport)
        self.games = GamesResource(self.transport)
        self.players = PlayersResource(self.transport)
        self.events = EventsResource(self.transport)
        self.teams = TeamsResource(self.transport)

    # Convenience pass-throughs so callers rarely need .transport directly.

    def login(self) -> None:
        self.transport.login()

    def logout(self) -> None:
        self.transport.logout()

    def get(self, path: str, params: Params | None = None) -> Any:
        """GET any v3 path — escape hatch for unwrapped endpoints."""
        return self.transport.get(path, params)

    @property
    def session(self) -> Any:
        return self.transport.session


__all__ = [
    "SportlogiqV3",
    "SportlogiqError",
    "Transport",
    "Resource",
    "QueryFilters",
    "EventOptions",
    "Params",
    "MetricsResource",
    "GamesResource",
    "PlayersResource",
    "EventsResource",
    "TeamsResource",
    "extract_events",
    "extract_player_events",
    "AggregationType",
    "BoxscoreMode",
    "EventMode",
    "Arena",
    "AverageGranularity",
    "CollectionScope",
    "CollectionType",
    "GameReportName",
    "LeagueReportName",
    "ManpowerSituation",
    "PathSeasonStage",
    "PeriodType",
    "Perspective",
    "Position",
    "SeasonStage",
]
