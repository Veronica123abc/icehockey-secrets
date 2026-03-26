from __future__ import annotations
from hockey.model.game import Game
import numpy as  np
import pandas as pd
from collections import defaultdict

def _successful_pass_reception_pairs(df: pd.DataFrame, team_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    team_events = df.loc[df["team_id"] == team_id]

    successful_passes = team_events.loc[
        (team_events["name"] == "pass") &
        (team_events["outcome"] == "successful"),
        ["x_adj_coord", "y_adj_coord", "zone"]
    ].copy()

    successful_receptions = team_events.loc[
        (team_events["name"] == "reception") &
        (team_events["outcome"] == "successful"),
        ["x_adj_coord", "y_adj_coord", "zone"]
    ].copy()

    pair_count = min(len(successful_passes), len(successful_receptions))
    if pair_count == 0:
        return successful_passes.iloc[0:0], successful_receptions.iloc[0:0]

    return (
        successful_passes.iloc[:pair_count].reset_index(drop=True),
        successful_receptions.iloc[:pair_count].reset_index(drop=True),
    )

def pass_length(game: Game):
    df_raw = game.events_raw_df()
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {}

    for team_id in team_ids:
        successful_passes, successful_receptions = _successful_pass_reception_pairs(df_raw, team_id)

        if successful_passes.empty:
            res[team_id] = successful_passes.assign(pass_distance=pd.Series(dtype=float))
            continue

        pass_xy = successful_passes[["x_adj_coord", "y_adj_coord"]].to_numpy()
        reception_xy = successful_receptions[["x_adj_coord", "y_adj_coord"]].to_numpy()
        distances = np.linalg.norm(pass_xy - reception_xy, axis=1)

        res[team_id] = successful_passes.assign(pass_distance=distances)

    return res


def oz_center_crosses(game:Game):
    df_raw = game.events_raw_df()
    team_ids = [game.info.home_team.id, game.info.away_team.id]
    res = {}
    for team_id in team_ids:
        successful_passes, successful_receptions = _successful_pass_reception_pairs(df_raw, team_id)

        if successful_passes.empty:
            res[team_id] = successful_passes.assign(pass_distance=pd.Series(dtype=float))
            continue


        pass_xy = list(successful_passes[["x_adj_coord", "y_adj_coord", "zone"]].itertuples(index=False, name=None))
        reception_xy = list(successful_receptions[["x_adj_coord", "y_adj_coord", "zone"]].itertuples(index=False, name=None))
        cross_center = [p[0][1]*p[1][1] < 0 for p in zip(pass_xy, reception_xy)]
        #distances = np.linalg.norm(pass_xy - reception_xy, axis=1)

        res[team_id] = sum(cross_center)
    return res

if __name__ == "__main__":
    from pathlib import Path
    from hockey.config.settings import Settings
    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    settings = Settings.from_env(project_root=Path("."))
    raw = RawGame(game_id=137536, root_dir=settings.data_root_dir)
    game = build_game(raw)
    res_c = oz_center_crosses(game)
    print(res_c)
    res = pass_length(game)

    print(f"{'Team':<20} {'# passes':<10} {'distance (tot feet)':<20} {'distance (avg feet)':20}")
    for team_id, event_data in res.items():
        team_name = game.info.home_team.name if game.info.home_team.id == team_id else game.info.away_team.name
        num_passes = len(event_data["pass_distance"])
        total_distance = np.sum(event_data["pass_distance"])
        average_distance = total_distance / num_passes if num_passes else 0.0
        print(f"{team_name:<20} {num_passes:<10} {round(total_distance):<20} {average_distance:<20.2f}")
