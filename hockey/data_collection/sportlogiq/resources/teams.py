"""Endpoints tagged ``Teams`` in the v3 spec."""

from __future__ import annotations

from typing import Any, Sequence

from .._transport import Resource
from ..filters import Params, array, scalar


class TeamsResource(Resource):
    """``api.teams`` — team lookup and external references."""

    def list(
        self,
        *,
        leagueid: Sequence[str | int] = (),
        withreferences: bool | None = None,
    ) -> Any:
        """GET /api/v3/teams — all teams, optionally scoped to leagues.

        ``leagueid`` must be sent as a ``leagueid[]`` array; the API rejects a
        bare scalar with "Value expected to be 'array', but 'string' given".
        Passing a list here handles that.
        """
        params: Params = array("leagueid", leagueid)
        params += scalar("withreferences", withreferences)
        return self._t.get("/api/v3/teams", params)

    def get(self, team_id: str | int, *, withreferences: bool | None = None) -> Any:
        """GET /api/v3/teams/{teamId}"""
        return self._t.get(
            f"/api/v3/teams/{team_id}", scalar("withreferences", withreferences)
        )

    def xdbref(self, season_id: str | int, xref_name: str) -> Any:
        """GET /api/v3/seasons/{seasonId}/teams/xdbref/{xrefName}

        Season-wide team id mapping for one external database.
        """
        return self._t.get(f"/api/v3/seasons/{season_id}/teams/xdbref/{xref_name}")
