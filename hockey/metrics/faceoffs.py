from __future__ import annotations
from hockey.model.game import Game

def faceoff_events(game: Game):
    """
    Return supplier faceoff rows with only the fields needed for faceoff metrics.
    """
    df = game.events_raw_df()

    required_columns = {"name", "team_id_in_possession", "outcome", "team_id"}
    if not required_columns.issubset(df.columns):
        return df.iloc[0:0].copy()

    return df[
        (df["name"] == "faceoff") &
        (df["team_id"].notna()) &
        (df["outcome"].isin(["successful"]))
    ][["team_id"]].copy()


def faceoff_wins_losses(game: Game) -> dict[int, dict[str, int]]:
    """
    Count faceoff wins and losses for each team in a single game.

    Interpretation:
    - outcome == "successful" -> win for team_id_in_possession
    - outcome == "failed"     -> loss for team_id_in_possession
    """
    faceoffs = faceoff_events(game)
    ht_wins = len(faceoffs[(faceoffs["team_id"] == game.info.home_team.id)])
    at_wins = len(faceoffs[(faceoffs["team_id"] == game.info.away_team.id)])

    result = {
        game.info.home_team.id: {"wins": ht_wins, "losses": at_wins},
        game.info.away_team.id: {"wins": at_wins, "losses": ht_wins}
    }
    return result


def faceoff_win_pct(game: Game) -> dict[int, float | None]:
    """
    Faceoff win percentage per team.

    Returns None for teams with zero recorded wins/losses.
    """
    counts = faceoff_wins_losses(game)
    out: dict[int, float | None] = {}

    for team_id, values in counts.items():
        wins = values["wins"]
        losses = values["losses"]
        total = wins + losses
        out[team_id] = None if total == 0 else round((wins / total), 2)

    return out


if __name__ == "__main__":
    from pathlib import Path
    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    settings = Settings.from_env(project_root=Path("."))
    raw = RawGame(game_id=137536, root_dir=settings.data_root_dir)
    game = build_game(raw)

    counts = faceoff_wins_losses(game)
    pct = faceoff_win_pct(game)

    print(counts)
    print(pct)
