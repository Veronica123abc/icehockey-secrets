"""Endpoints tagged ``Players`` in the v3 spec."""

from __future__ import annotations

from typing import Any, Sequence

from .._transport import Resource
from ..enums import SeasonStage
from ..filters import (
    GAME_HISTORY_FILTERS,
    Params,
    QueryFilters,
    array,
    combine,
    scalar,
)

PLAYER_SEARCH_FILTERS = frozenset({"teamid", "playerid"})
"""/api/v3/players shares only these two fields with the filter vocabulary."""


class PlayersResource(Resource):
    """``api.players`` — player search, game history, external references."""

    def search(
        self,
        *,
        keyword: str | None = None,
        firstname: str | None = None,
        lastname: str | None = None,
        dob: str | None = None,
        dbname: str | None = None,
        refid: str | None = None,
        teamid: Sequence[str | int] = (),
        playerid: Sequence[str | int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        updatedsince: str | None = None,
        includeteaminsearch: bool | None = None,
        withreferences: bool | None = None,
        withseasonsummaries: bool | None = None,
        withstatuses: bool | None = None,
        applyfilterstoseasonsummaries: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/players — find players matching search criteria.

        The endpoint's validation is stricter than the spec suggests. It needs
        either an *identity* or a *season + scope*:

        * identity — ``keyword``, or ``playerid``, or ``firstname`` **and**
          ``lastname`` together
        * season + scope — ``seasonid`` **and** ``seasonstage``, plus at least
          one of ``leagueid`` or ``teamid``

        Anything less returns 400 "Params not set correctly": ``seasonid`` +
        ``seasonstage`` with no scope, ``teamid`` with no season, ``lastname``
        alone. The two styles do not mix either — ``keyword`` + ``leagueid``
        is rejected.

        Sequence arguments accept a bare value as shorthand, so
        ``teamid=1, seasonstage="regular"`` works the same as
        ``teamid=[1], seasonstage=["regular"]``.

        ``withreferences``, ``withstatuses`` and ``withseasonsummaries``
        combine with any working criterion. ``applyfilterstoseasonsummaries``
        does not: with a ``teamid`` search it returns HTTP 500 with a leaked
        SQL error (``column reference "teamid" is ambiguous``). That is a
        server-side bug, so avoid the flag.

        ``teamid`` and ``playerid`` are the two fields this endpoint shares
        with the API-wide vocabulary; pass them directly, or via ``filters``
        if reusing an existing :class:`QueryFilters`, but not both. If
        ``seasonstage`` is omitted the API defaults to
        ``["regular", "playoffs"]``.

        ``applyfilterstoseasonsummaries`` applies the same filters to the
        summaries added by ``withseasonsummaries``, rather than returning
        career-wide ones.
        """
        params: Params = []
        params += scalar("keyword", keyword)
        params += scalar("firstname", firstname)
        params += scalar("lastname", lastname)
        params += scalar("dob", dob)
        params += scalar("dbname", dbname)
        params += scalar("refid", refid)
        params += array("leagueid", leagueid)
        params += array("seasonid", seasonid)
        params += array("seasonstage", seasonstage)
        params += scalar("updatedsince", updatedsince)
        params += scalar("includeteaminsearch", includeteaminsearch)
        params += scalar("withreferences", withreferences)
        params += scalar("withseasonsummaries", withseasonsummaries)
        params += scalar("withstatuses", withstatuses)
        params += scalar(
            "applyfilterstoseasonsummaries", applyfilterstoseasonsummaries
        )
        params += combine(
            {"teamid": teamid, "playerid": playerid},
            filters,
            PLAYER_SEARCH_FILTERS,
        )
        return self._t.get("/api/v3/players", params)

    def for_team(
        self,
        team_id: str | int,
        season_id: str | int,
        season_stage: Sequence[SeasonStage] = ("regular",),
        **kwargs: Any,
    ) -> list[dict]:
        """Every player on a team's roster for a season — the list, unwrapped.

        Wraps the one :meth:`search` combination that accepts a team filter
        (``teamid`` + ``seasonid`` + ``seasonstage``, all required) and returns
        ``payload["players"]`` directly.

        This is roster membership for the season, not proof of ice time. For
        players who actually appeared in a given game, use
        :meth:`GamesResource.rosters`; for those with recorded events, go via
        :meth:`EventsResource.player_events`.
        """
        payload = self.search(
            teamid=[team_id],
            seasonid=[season_id],
            seasonstage=list(season_stage),
            **kwargs,
        )
        return payload.get("players") or []

    def ids_for_team(
        self,
        team_id: str | int,
        season_id: str | int,
        season_stage: Sequence[SeasonStage] = ("regular",),
    ) -> list[str]:
        """Just the player ids from :meth:`for_team`."""
        return [player["id"] for player in self.for_team(team_id, season_id, season_stage)]

    def game_history(
        self,
        player_id: str | int,
        *,
        teamid: Sequence[str | int] = (),
        leagueid: Sequence[str | int] = (),
        seasonid: Sequence[str | int] = (),
        seasonstage: Sequence[SeasonStage] = (),
        from_: str | None = None,
        to: str | None = None,
        withgames: bool | None = None,
        filters: QueryFilters | None = None,
    ) -> Any:
        """GET /api/v3/players/{playerId}/gamehistory — games a player appeared in.

        ``from_``/``to`` are ISO 8601 UTC and inclusive.
        """
        params: Params = []
        params += array("leagueid", leagueid)
        params += array("seasonid", seasonid)
        params += array("seasonstage", seasonstage)
        params += scalar("withgames", withgames)
        params += combine(
            {"teamid": teamid, "from": from_, "to": to},
            filters,
            GAME_HISTORY_FILTERS,
        )
        return self._t.get(f"/api/v3/players/{player_id}/gamehistory", params)

    def xdbref(self, season_id: str | int, xref_name: str) -> Any:
        """GET /api/v3/seasons/{seasonId}/players/xdbref/{xrefName}

        Season-wide player id mapping for one external database.
        """
        return self._t.get(
            f"/api/v3/seasons/{season_id}/players/xdbref/{xref_name}"
        )
