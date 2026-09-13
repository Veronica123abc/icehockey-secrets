from __future__ import annotations

import datetime
from dataclasses import dataclass, field



@dataclass
class Competition:
    id: int
    name: str
    seasons: list[Season]
    raw: dict = field(default_factory=dict)


@dataclass
class Season:
    name: str
    stages: list[Stage]

@dataclass
class Stage:
    name: str
    start_date: datetime.datetime
    end_date: datetime.datetime

