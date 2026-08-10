"""Endpoints tagged ``Games`` in the v3 spec, plus the closely-related
``/shifts`` (tagged ``Situations``/``Games``) and ``/trackingassets``.

Convention used here and in the other resources:

* Endpoints taking only a handful of plain id/date filters (``teamid``,
  ``playerid``, ``period``, ``from``/``to``) expose them as ordinary keyword
  arguments — :meth:`GamesResource.list` and the event streams.
* Endpoints taking the large situational block (``mps``, ``mpsskaters``,
  ``woi``, ``scoredifferential``, ...) take a :class:`QueryFilters` instead,
  because spelling out 8–16 arguments is worse — :meth:`GamesResource.context`,
  :meth:`GamesResource.shifts`, and the metrics resource.
* The first group still accepts ``filters=`` for callers reusing a
  ``QueryFilters`` built elsewhere. Supplying the same field both ways raises
  ``ValueError`` rather than silently sending it twice.
"""

from __future__ import annotations

from typing import Any, Sequence

from .._transport import Resource
from ..enums import BoxscoreMode, SeasonStage
from ..filters import (
    GAME_CONTEXT_FILTERS,
    GAMES_FILTERS,
    SHIFTS_FILTERS,
    Params,
    QueryFilters,
    array,
    combine,
    scalar,
)


class GamesResource(Resource):
    """``api.games`` — schedules, per-game detail, rosters, shifts."""

    def list(
        self,
        *,
        gameid: Sequence[str | int] = (),
        teamid: Sequence[str | int] = (),
        playerid: Sequence[str | int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        from_: str | None = None,
        to: str | None = None,
        vidparamid: Sequence[str | int] = (),
        vidid: Sequence[str | int] = (),
        withstates: bool | None = None,
        withreferences: bool | None = None,
        hasroster: bool | None = None,
        withvidparams: bool | None = None,
        withscores: bool | None = None,
        withtoi: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/games — the schedule, filtered.

        ``from_``/``to`` are ISO 8601 UTC and inclusive. If ``seasonstage`` is
        omitted the API defaults to ``["regular", "playoffs"]``.

        ``withtoi`` is only honoured when filtering by ``playerid``. The spec's
        ``withstate`` (singular) is deprecated for this endpoint in favour of
        ``withstates`` and is not exposed.
        """
        params: Params = []
        params += array("gameid", gameid)
        params += array("leagueid", leagueid)
        params += array("seasonid", seasonid)
        params += array("seasonstage", seasonstage)
        params += array("vidparamid", vidparamid)
        params += array("vidid", vidid)
        params += scalar("withstates", withstates)
        params += scalar("withreferences", withreferences)
        params += scalar("hasroster", hasroster)
        params += scalar("withvidparams", withvidparams)
        params += scalar("withscores", withscores)
        params += scalar("withtoi", withtoi)
        params += combine(
            {"teamid": teamid, "playerid": playerid, "from": from_, "to": to},
            filters,
            GAMES_FILTERS,
        )
        return self._t.get("/api/v3/games", params)

    def get(
        self,
        game_id: str | int,
        *,
        withstate: bool | None = None,
        withreferences: bool | None = None,
        withperiods: bool | None = None,
        withvidparams: bool | None = None,
        withscores: bool | None = None,
    ) -> Any:
        """GET /api/v3/games/{gameId} — details for one game."""
        params: Params = []
        params += scalar("withstate", withstate)
        params += scalar("withreferences", withreferences)
        params += scalar("withperiods", withperiods)
        params += scalar("withvidparams", withvidparams)
        params += scalar("withscores", withscores)
        return self._t.get(f"/api/v3/games/{game_id}", params)

    def state(self, game_id: str | int) -> Any:
        """GET /api/v3/games/{gameId}/state"""
        return self._t.get(f"/api/v3/games/{game_id}/state")

    def context(
        self, game_id: str | int, filters: QueryFilters | None = None
    ) -> Any:
        """GET /api/v3/games/{gameId}/gamecontext

        Accepts the manpower/period/team/player slice of the filter vocabulary.
        """
        params = filters.to_params(GAME_CONTEXT_FILTERS) if filters else []
        return self._t.get(f"/api/v3/games/{game_id}/gamecontext", params)

    def scores(self, game_id: str | int) -> Any:
        """GET /api/v3/games/{gameId}/scores"""
        return self._t.get(f"/api/v3/games/{game_id}/scores")

    def boxscore(
        self, game_id: str | int, mode: BoxscoreMode | None = None
    ) -> Any:
        """GET /api/v3/games/{gameId}/boxscore — ``mode`` defaults to compiled."""
        return self._t.get(
            f"/api/v3/games/{game_id}/boxscore", scalar("mode", mode)
        )

    def rosters(
        self,
        game_id: str | int,
        *,
        withpersons: bool | None = None,
        withreferences: bool | None = None,
    ) -> Any:
        """GET /api/v3/games/{gameId}/rosters"""
        params: Params = []
        params += scalar("withpersons", withpersons)
        params += scalar("withreferences", withreferences)
        return self._t.get(f"/api/v3/games/{game_id}/rosters", params)

    def xrefs(self, game_id: str | int) -> Any:
        """GET /api/v3/games/{gameId}/xrefs — external database references."""
        return self._t.get(f"/api/v3/games/{game_id}/xrefs")

    def xdbref(self, season_id: str | int, xref_name: str) -> Any:
        """GET /api/v3/seasons/{seasonId}/games/xdbref/{xrefName}

        Season-wide game id mapping for one external database.
        """
        return self._t.get(f"/api/v3/seasons/{season_id}/games/xdbref/{xref_name}")

    def tracking_assets(self, game_id: str | int) -> Any:
        """GET /api/v3/games/{gameId}/trackingassets"""
        return self._t.get(f"/api/v3/games/{game_id}/trackingassets")

    def shifts(
        self,
        *,
        gameid: Sequence[str | int] = (),
        seasonid: str | int | None = None,
        seasonstage: SeasonStage | None = None,
        leagueid: str | int | None = None,
        teamid: str | int | None = None,
        lastxgames: int | None = None,
        mpsteamid: Sequence[str | int] = (),
        opposingposition: Sequence[str] = (),
        together: bool | None = None,
        strictplayers: bool | None = None,
        withvidparams: bool | None = None,
        withgames: bool | None = None,
        includeshiftsentrycomplete: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/shifts — player shift situations.

        Requires at least one of ``playerid``/``opposingplayerid`` via
        ``filters``; without one the API returns 400. When ``gameid`` is given,
        those players must appear on that game's roster or it returns 404 —
        :meth:`rosters` is the way to check.

        This endpoint is the odd one out: ``seasonid``, ``seasonstage``,
        ``leagueid`` and ``teamid`` are scalars here, where most endpoints take
        arrays. ``teamid`` is therefore an explicit argument and is excluded
        from :data:`SHIFTS_FILTERS`; passing it via ``filters`` has no effect.

        ``together`` selects whether the requested players must have been on
        ice simultaneously; ``strictplayers`` requires both ``teamid`` and
        ``together`` to be meaningful.
        """
        params: Params = []
        params += array("gameid", gameid)
        params += scalar("seasonid", seasonid)
        params += scalar("seasonstage", seasonstage)
        params += scalar("leagueid", leagueid)
        params += scalar("teamid", teamid)
        params += scalar("lastxgames", lastxgames)
        params += array("mpsteamid", mpsteamid)
        params += array("opposingposition", opposingposition)
        params += scalar("together", together)
        params += scalar("strictplayers", strictplayers)
        params += scalar("withvidparams", withvidparams)
        params += scalar("withgames", withgames)
        params += scalar("includeshiftsentrycomplete", includeshiftsentrycomplete)
        if filters:
            params += filters.to_params(SHIFTS_FILTERS)
        return self._t.get("/api/v3/shifts", params)
