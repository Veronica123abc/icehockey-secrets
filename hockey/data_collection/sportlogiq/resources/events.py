"""Raw event streams and their definitions.

Covers the ``Game Events``, ``Player Events`` and ``Player Shift Events`` tags.
The event-type definition endpoints live here too rather than in a separate
definitions module — they exist to decode the streams' ``defId``/``flagId``
fields, so keeping them adjacent is more useful than mirroring the spec's
``Definitions`` tag.

The three stream endpoints share a scoping vocabulary — ``gameid``,
``teamid``, ``playerid``, ``period``, ``leagueid``, ``seasonid``,
``seasonstage`` — all available as plain keyword arguments. Each adds its own
extras. ``filters=`` is also accepted for reusing an existing
:class:`QueryFilters`, but only contributes ``teamid``/``playerid``/``period``,
and raises if it collides with a keyword argument.
"""

from __future__ import annotations

from typing import Any, Sequence

from .._transport import Resource
from ..enums import EventMode, SeasonStage
from ..filters import (
    EVENT_STREAM_FILTERS,
    Params,
    QueryFilters,
    array,
    combine,
    scalar,
)


def extract_player_events(payload: Any) -> list[Any]:
    """Pull the event rows out of a :meth:`EventsResource.player_events` payload.

    That endpoint returns a bare list normally, but wraps it in a
    ``{"playerEvents": ...}`` envelope when ``withplayers`` or
    ``withflagdefinitions`` is set. This normalises both.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        events = payload.get("playerEvents")
        if isinstance(events, list):
            return events
    return []


def _scope_params(
    gameid: Sequence[str | int],
    teamid: Sequence[str | int],
    playerid: Sequence[str | int],
    period: Sequence[int],
    leagueid: Sequence[str | int],
    seasonid: Sequence[str | int],
    seasonstage: Sequence[SeasonStage],
    filters: QueryFilters | None,
) -> Params:
    """The scoping block common to the three event streams."""
    params: Params = []
    params += array("gameid", gameid)
    params += array("leagueid", leagueid)
    params += array("seasonid", seasonid)
    params += array("seasonstage", seasonstage)
    params += combine(
        {"teamid": teamid, "playerid": playerid, "period": period},
        filters,
        EVENT_STREAM_FILTERS,
    )
    return params


class EventsResource(Resource):
    """``api.events`` — game events, player events, shift events, definitions."""

    # -- streams -----------------------------------------------------------

    def game_events(
        self,
        *,
        gameeventid: Sequence[str | int] = (),
        gameeventname: Sequence[str] = (),
        gameid: Sequence[str | int] = (),
        teamid: Sequence[str | int] = (),
        playerid: Sequence[str | int] = (),
        period: Sequence[int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        includeoutofsequenceevents: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/gameevents — goals, penalties, faceoffs and the like.

        Names for ``gameeventname`` come from :meth:`game_event_definitions`.
        """
        params: Params = []
        params += array("gameeventid", gameeventid)
        params += array("gameeventname", gameeventname)
        params += _scope_params(
            gameid, teamid, playerid, period, leagueid, seasonid, seasonstage,
            filters,
        )
        params += scalar("includeoutofsequenceevents", includeoutofsequenceevents)
        return self._t.get("/api/v3/gameevents", params)

    def player_events(
        self,
        *,
        playereventid: Sequence[str | int] = (),
        playereventname: Sequence[str] = (),
        gameid: Sequence[str | int] = (),
        teamid: Sequence[str | int] = (),
        playerid: Sequence[str | int] = (),
        period: Sequence[int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        mode: EventMode | None = None,
        excludegameevents: bool | None = None,
        withplayers: bool | None = None,
        withflagdefinitions: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/playerevents — the per-action event stream.

        This is the v3 counterpart of the v1 ``playsequence`` data. ``mode``
        defaults to ``compiled``. ``withflagdefinitions`` inlines the flag
        lookup so you do not need a second call to :meth:`flag_definitions`.

        **The response shape depends on the flags.** With neither
        ``withplayers`` nor ``withflagdefinitions`` the payload is a bare list
        of events; setting *either* one switches it to
        ``{"playerEvents": [...], "players": ..., "flagDefinitions": ...}``.
        Use :func:`extract_player_events` to handle both.
        """
        params: Params = []
        params += array("playereventid", playereventid)
        params += array("playereventname", playereventname)
        params += _scope_params(
            gameid, teamid, playerid, period, leagueid, seasonid, seasonstage,
            filters,
        )
        params += scalar("mode", mode)
        params += scalar("excludegameevents", excludegameevents)
        params += scalar("withplayers", withplayers)
        params += scalar("withflagdefinitions", withflagdefinitions)
        return self._t.get("/api/v3/playerevents", params)

    def player_shift_events(
        self,
        *,
        gameid: Sequence[str | int] = (),
        teamid: Sequence[str | int] = (),
        playerid: Sequence[str | int] = (),
        period: Sequence[int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/playershiftevents — shift starts/ends per player.

        Distinct from :meth:`GamesResource.shifts`, which returns aggregated
        shift *situations* rather than the raw events.
        """
        return self._t.get(
            "/api/v3/playershiftevents",
            _scope_params(
                gameid, teamid, playerid, period, leagueid, seasonid,
                seasonstage, filters,
            ),
        )

    def reference_player_events(
        self,
        game_id: str | int,
        *,
        sourceid: Sequence[str | int] = (),
        period: Sequence[int] = (),
        withsources: bool | None = None,
        witheventdefinitions: bool | None = None,
    ) -> Any:
        """GET /api/v3/games/{gameId}/referenceplayerevents

        Third-party (league-supplied) events for cross-checking, keyed by
        source. Takes ``period`` directly rather than through ``filters``,
        since it accepts none of the rest of the vocabulary.
        """
        params: Params = []
        params += array("sourceid", sourceid)
        params += array("period", period)
        params += scalar("withsources", withsources)
        params += scalar("witheventdefinitions", witheventdefinitions)
        return self._t.get(
            f"/api/v3/games/{game_id}/referenceplayerevents", params
        )

    # -- definitions -------------------------------------------------------

    def game_event_definitions(self) -> Any:
        """GET /api/v3/definitions/gameevents — all game event types."""
        return self._t.get("/api/v3/definitions/gameevents")

    def player_event_definitions(self, defid: Sequence[str | int] = ()) -> Any:
        """GET /api/v3/definitions/playerevents

        Decodes the ``defId`` field on player events.
        """
        return self._t.get(
            "/api/v3/definitions/playerevents", array("defid", defid)
        )

    def flag_definitions(self, flagid: Sequence[str | int] = ()) -> Any:
        """GET /api/v3/definitions/flags — event flag lookup."""
        return self._t.get("/api/v3/definitions/flags", array("flagid", flagid))

    def player_shift_event_definitions(self) -> Any:
        """GET /api/v3/definitions/playershiftevent

        Note the singular ``playershiftevent`` in this path, unlike the plural
        used by the stream endpoint. That asymmetry is in the spec.
        """
        return self._t.get("/api/v3/definitions/playershiftevent")
