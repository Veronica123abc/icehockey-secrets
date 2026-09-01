from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class RawGame:
    """
    Lazy, cached access to the 5 JSON files for a game.

    Responsibilities:
      - know where files live
      - load JSON on demand
      - cache results
    """
    game_id: int
    root_dir: Path  # points to directory that contains folders per game_id, or directly files (see _path_for)
    auto_download: bool = False  # prompt and download from Sportlogiq API if files are missing
    playsequence_source: str = "playsequence"  # stem of the playsequence file: "playsequence" or "playsequence_compiled"
    _cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def _path_for(self, stem: str) -> Path:
        return self.root_dir / str(self.game_id) / f"{stem}.json"

    def _load(self, stem: str) -> Any:
        if stem not in self._cache:
            path = self._path_for(stem)
            try:
                with path.open("r", encoding="utf-8") as f:
                    self._cache[stem] = json.load(f)
            except FileNotFoundError:
                if not self.auto_download:
                    raise
                from hockey.data_collection.sportlogiq_api import prompt_and_download_game
                downloaded = prompt_and_download_game(self.game_id, self.root_dir)
                if not downloaded:
                    raise
                with path.open("r", encoding="utf-8") as f:
                    self._cache[stem] = json.load(f)
        return self._cache[stem]

    @property
    def game_info(self) -> dict:
        return self._load("game-info")

    @property
    def playsequence(self) -> dict:
        return self._load(self.playsequence_source)

    @property
    def playsequence_raw(self) -> dict:
        return self._load("playsequence")

    @property
    def playsequence_compiled(self) -> dict:
        return self._load("playsequence_compiled")



    @property
    def roster(self) -> dict:
        return self._load("roster")

    @property
    def player_toi(self) -> dict:
        return self._load("playerTOI")

    # def _full_events_by_key(self) -> dict[tuple[float, int, str], dict]:
    #
    #     """
    #     Lazy index of playsequence.json keyed by (current_possession, current_play_in_possession).
    #     Always loads the full (non-compiled) playsequence regardless of playsequence_source.
    #     Built once and cached; the first event at each key wins if timestamps collide.
    #     """
    #     cache_key = "_full_events_by_key"
    #     if cache_key not in self._cache:
    #         data = self._load("playsequence")
    #         idx: dict[tuple[int, int, str], dict] = {}
    #         events = data.get("events", [])
    #         events = [e for e in events if e["name"] == "shot"]
    #         for e in events:
    #             k = (int(e["current_possession"]), int(e["current_play_in_possession"]), str(e.get("name", "")))
    #             idx.setdefault(k, e)
    #         self._cache[cache_key] = idx
    #     return self._cache[cache_key]
    # -- linking compiled events back to playsequence.json ---------------------
    #
    # playsequence_compiled.json carries the events we compute metrics from, but
    # only playsequence.json carries the on-ice rosters
    # (team_forwards_on_ice_refs and friends). There is no shared event id, so
    # the two files are joined on (current_possession, current_play_in_possession)
    # in three steps -- see full_event_for(). Everything here is lazy: the 7.9 MB
    # playsequence.json is not read unless someone asks for a link.

    _NO_POSSESSION = (0, 0)   # sentinel in compiled: event has no possession context

    @staticmethod
    def _possession_key(e: dict) -> tuple:
        return (e.get("current_possession"), e.get("current_play_in_possession"))

    @staticmethod
    def _direct_key(e: dict) -> tuple:
        """Fallback key, for events the possession key can't reach."""
        player = e.get("player_reference_id")
        if player is None:
            player = e.get("player_id")
        return (round(float(e["game_time"]), 2), e.get("name"), str(player or ""))

    def _link_indexes(self) -> tuple[dict, dict, dict]:
        cache_key = "_link_indexes"
        if cache_key not in self._cache:
            full = self._load("playsequence").get("events", [])
            by_possession: dict[tuple, dict] = {}
            by_direct: dict[tuple, list] = {}
            for e in full:
                key = self._possession_key(e)
                # A real possession key is unique in playsequence.json; the
                # sentinel and nulls are not, so they must never index.
                if key[0] is not None and key != self._NO_POSSESSION:
                    by_possession.setdefault(key, e)
                by_direct.setdefault(self._direct_key(e), []).append(e)
            compiled = self._load("playsequence_compiled").get("events", [])
            by_id = {e["event_id"]: e for e in compiled}
            self._cache[cache_key] = (by_possession, by_direct, by_id)
        return self._cache[cache_key]

    def full_event_for(self, compiled_event: dict) -> dict | None:
        """The playsequence.json event matching a playsequence_compiled event.

        Three steps, because neither file carries an id the other shares:

        1. Join on (current_possession, current_play_in_possession). Exact where
           it is defined -- unique on the full side, and the joined events agree
           on game_time to within 0.5s.
        2. Compiled marks "no possession context" as (0, 0) rather than null,
           and 41% of events carry it. Those are derived events, so follow
           base_event_id to their base event and use *its* possession key. Never
           look (0, 0) up directly: playsequence.json has exactly one event with
           that key, so it would silently match everything to the same event.
        3. What is left (faceoffs, loose-puck recoveries, penalties -- events
           genuinely outside a possession) falls back to
           (game_time, name, player), accepted only when it is unambiguous.
        """
        by_possession, by_direct, by_id = self._link_indexes()

        key = self._possession_key(compiled_event)
        if key == self._NO_POSSESSION:
            base = by_id.get(compiled_event.get("base_event_id"))
            if base is not None:
                key = self._possession_key(base)

        if key[0] is not None and key != self._NO_POSSESSION:
            match = by_possession.get(key)
            if match is not None:
                return match

        candidates = by_direct.get(self._direct_key(compiled_event), ())
        return candidates[0] if len(candidates) == 1 else None

    # Fields playsequence.json carries and playsequence_compiled.json drops.
    ON_ICE_FIELDS = (
        "team_forwards_on_ice_refs",
        "team_defencemen_on_ice_refs",
        "team_goalie_on_ice_ref",
        "opposing_team_forwards_on_ice_refs",
        "opposing_team_defencemen_on_ice_refs",
        "opposing_team_goalie_on_ice_ref",
    )
    METRIC_FIELDS = (
        "play_section",
        "expected_goals_all_shots",
        "expected_goals_all_shots_grade",
        "expected_goals_on_net",
        "expected_goals_on_net_grade",
    )
    LINKED_FIELDS = ON_ICE_FIELDS + METRIC_FIELDS

    def linked_fields_for(self, compiled_event: dict) -> dict:
        """Every playsequence.json-only field for a compiled event.

        The on-ice rosters plus the expected-goals metrics and play_section.
        Empty when the event could not be linked -- an empty dict means
        "unknown", not "absent".
        """
        full = self.full_event_for(compiled_event)
        if full is None:
            return {}
        return {key: full.get(key) for key in self.LINKED_FIELDS}

    def on_ice_for(self, compiled_event: dict) -> dict:
        """On-ice player references for a compiled event, or empty lists."""
        linked = self.linked_fields_for(compiled_event)
        return {key: linked[key] for key in self.ON_ICE_FIELDS if key in linked}

    def _full_events_by_key(self) -> dict[tuple[float, int], dict]:
        """
        Lazy index of playsequence.json keyed by (current_possession, current_play_in_possession).
        Always loads the full (non-compiled) playsequence regardless of playsequence_source.
        Built once and cached; the first event at each key wins if timestamps collide.
        """
        cache_key = "_full_events_by_key"
        if cache_key not in self._cache:
            data = self._load("playsequence")
            idx: dict[tuple[int, int], dict] = {}
            events = data.get("events", [])
            events = [e for e in events if e["team_in_possession"] not in  ['None', 'none', None]]
            for e in events:
                k = (int(e["current_possession"]), int(e["current_play_in_possession"]))
                idx.setdefault(k, e)
            self._cache[cache_key] = idx
        return self._cache[cache_key]

    def full_event_field(self, current_possession: int, current_play_in_possession: int, name: str, field: str, default: Any = None) -> Any:
        """
        Return a field from the full playsequence event at (game_time, name).
        The field 'playsection' is not used in playsequence_compiled. To fetch this, the matching event in the
        raw playsequence need to be fetched. This is a temporary hack. game_time is a float, non-unique variable which
        is not suitable to query.
        """
        e = self._full_events_by_key().get((current_possession, current_play_in_possession)) #, name))
        return e.get(field, default) if e is not None else default

    def full_event_field_2(self, current_possession: int, current_play_in_possession: int, default: Any = None) -> Any:
        """
        Return a field from the full playsequence event at (game_time, name).
        The field 'playsection' is not used in playsequence_compiled. To fetch this, the matching event in the
        raw playsequence need to be fetched. This is a temporary hack. game_time is a float, non-unique variable which
        is not suitable to query.
        """
        e = self._full_events_by_key().get((current_possession, current_play_in_possession))
        return e

    # def _full_events_by_key(self) -> dict[tuple[float, str], dict]:
    #     """
    #     Lazy index of playsequence.json keyed by (game_time, name).
    #     Always loads the full (non-compiled) playsequence regardless of playsequence_source.
    #     Built once and cached; the first event at each key wins if timestamps collide.
    #     """
    #     cache_key = "_full_events_by_key"
    #     if cache_key not in self._cache:
    #         data = self._load("playsequence")
    #         idx: dict[tuple[float, str], dict] = {}
    #         for e in data.get("events", []):
    #             k = (float(e["game_time"]), str(e.get("name", "")))
    #             idx.setdefault(k, e)
    #         self._cache[cache_key] = idx
    #     return self._cache[cache_key]
    #
    # def full_event_field(self, game_time: float, name: str, field: str, default: Any = None) -> Any:
    #     """
    #     Return a field from the full playsequence event at (game_time, name).
    #     The field 'playsection' is not used in playsequence_compiled. To fetch this, the matching event in the
    #     raw playsequence need to be fetched. This is a temporary hack. game_time is a float, non-unique variable which
    #     is not suitable to query.
    #     """
    #     e = self._full_events_by_key().get((game_time, name))
    #     return e.get(field, default) if e is not None else default