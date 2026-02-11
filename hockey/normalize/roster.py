from __future__ import annotations

from typing import Optional

from hockey.model.roster import Player, Roster


def _opt_str(x) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def normalize_roster(*, game_id: int, raw_roster: dict) -> Roster:
    """
    Your roster.json shape (per example):

    {
      "<team_id>": {"players": [ {"id": "...", "first_name": "...", ...}, ... ], "staff": [...]},
      "<team_id>": {...},
      "crew": []
    }

    We treat the outer keys (except "crew") as team ids and attach them to players.
    """
    players: dict[int, Player] = {}

    for team_key, team_blob in raw_roster.items():
        if team_key == "crew":
            continue
        if not isinstance(team_blob, dict):
            continue
        team_players = team_blob.get("players")
        if not isinstance(team_players, list):
            continue

        try:
            team_id = int(str(team_key).strip())
        except (TypeError, ValueError):
            team_id = None  # should not happen, but keep it safe

        for p in team_players:
            if not isinstance(p, dict):
                continue
            pid_raw = p.get("id")
            if pid_raw is None:
                continue
            try:
                pid = int(str(pid_raw).strip())
            except (TypeError, ValueError):
                continue

            players[pid] = Player(
                player_id=pid,
                team_id=team_id,
                first_name=_opt_str(p.get("first_name")),
                last_name=_opt_str(p.get("last_name")),
                position=_opt_str(p.get("position")),
            )

    return Roster(game_id=game_id, players=players)