"""Literal aliases mirroring the enums in the v3 OpenAPI spec.

Kept in one place so resource modules share a single vocabulary and editors can
autocomplete the accepted values.
"""

from __future__ import annotations

from typing import Literal

SeasonStage = Literal["training", "preseason", "regular", "playoffs"]
"""Season stage as accepted by query parameters."""

PathSeasonStage = Literal["preseason", "regular", "playoffs"]
"""Season stage in path parameters — the spec omits 'training' there."""

CollectionType = Literal["advancedStats", "linesAndPairs", "scouting", "faceOffs"]
CollectionScope = Literal["team", "opposingteam", "skater", "goalie"]
AggregationType = Literal["total", "sum", "customsum", "average", "max"]
AverageGranularity = Literal[
    "game", "period", "per2", "per15", "per20", "per45", "per60", "per90", "total"
]
ManpowerSituation = Literal["SH", "PP", "ES"]
PeriodType = Literal["regular", "overtime"]
Arena = Literal["home", "away"]
Position = Literal["F", "D", "G"]
Perspective = Literal["iCE"]
EventMode = Literal["compiled", "raw", "live"]
"""Event-processing mode, shared by /boxscore and /playerevents."""

BoxscoreMode = EventMode

GameReportName = Literal[
    "pregamesummary", "postgamesummary", "pregamecomplete", "postgamecomplete"
]
LeagueReportName = Literal[
    "pregamecomplete", "playercard", "dashboard", "tradstats", "rosterstats"
]
