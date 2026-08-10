"""One module per endpoint group, mirroring the spec's tags.

Implemented:

* :mod:`.metrics` — the 9 ``Metrics`` endpoints
* :mod:`.games`   — ``Games``, plus ``/shifts`` and ``/trackingassets``
* :mod:`.players` — ``Players``
* :mod:`.events`  — the three event streams, ``referenceplayerevents``, and
  the event-type/flag definitions
* :mod:`.teams`   — ``Teams``

Not implemented (nothing in the analysis pipeline needs them yet): playlists
(19 endpoints), watchlists (9), companies/users (6), and
``/definitions/playlistfolderspermissions``. Reach them through
``api.get(path, params)`` if needed.
"""

from __future__ import annotations

from .events import EventsResource, extract_player_events
from .games import GamesResource
from .metrics import MetricsResource, extract_events
from .players import PLAYER_SEARCH_FILTERS, PlayersResource
from .teams import TeamsResource

__all__ = [
    "EventsResource",
    "GamesResource",
    "MetricsResource",
    "PlayersResource",
    "TeamsResource",
    "PLAYER_SEARCH_FILTERS",
    "extract_events",
    "extract_player_events",
]
