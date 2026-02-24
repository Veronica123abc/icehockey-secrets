from __future__ import annotations
from hockey.io.raw_competition import RawCompetition
from hockey.model.competition import Competition, Season, Stage
from hockey.config.settings import Settings
import json
from pathlib import Path

def build_competition(raw_competition: RawCompetition) -> Competition:

    data = raw_competition.info
    competition_id = int(data["id"])
    competition_name = data["name"]
    seasons = []
    for season in data["seasons"]:
        new_season = Season(season["name"], stages=[])
        stages = []
        for stage in season["stages"]:
            new_stage = Stage(stage["name"], stage["start_date"], stage["end_date"])
            stages.append(new_stage)
        new_season.stages = stages
        seasons.append(new_season)

    return Competition(
        id=competition_id,
        name=competition_name,
        seasons=seasons,
        raw=data
    )

