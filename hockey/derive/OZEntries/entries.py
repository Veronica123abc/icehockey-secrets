from __future__ import annotations

from dataclasses import dataclass, field

from hockey.model.game import Game


@dataclass
class ManpowerSituation:
    team_skaters: int | None
    opposing_team_skaters: int | None


@dataclass
class ShotAfterEntry:
    time_since_entry: float  # seconds from zone entry to shot


@dataclass
class ZoneEntry:
    team_id: int
    entry_type: str          # "dumpin", "pass", or "carry"
    entry_time: float        # game time in seconds
    shots: list[ShotAfterEntry] = field(default_factory=list)
    recovered: bool | None = None  # True/False for dumpins; None for pass/carry
    goal: float = -1.0  # seconds from entry to goal; -1 if no goal
    manpower_situation: ManpowerSituation | None = None
    team_shift_toi: float | None = None
    opposing_team_shift_toi: float | None = None

    @property
    def shot_count(self) -> int:
        return len(self.shots)


def _classify_entry(event) -> str | None:
    """
    Classify an offensive-zone entry from a compiled playsequence event.

    Definitions (see hockey/derive/OZEntries/CLAUDE.md):
      - carry:  name == "controlledentry", type "carry..."
      - pass:   name == "controlledentry", type "pass..."
      - dumpin: name == "dumpinentry"

    The compiled `type` on controlledentry carries trailing flags
    (e.g. "carrywithplaywithshotonnet", "passwithplay"), so we match on the
    leading token rather than an exact string.
    """
    name = event.name
    if name == "controlledentry":
        etype = event.type
        if etype.startswith("carry"):
            return "carry"
        if etype.startswith("pass"):
            return "pass"
        return None
    if name == "dumpinentry":
        return "dumpin"
    return None


# Events that end the current OZ possession (a DZ exit by the defending team).
# Per hockey/derive/OZEntries/CLAUDE.md: name "dumpout" or "controlledexit".
# (The CLAUDE.md spells it "dumout"; the actual compiled event name is "dumpout".)
_ZONE_EXIT_NAMES = frozenset({"dumpout", "controlledexit"})


def _is_shot_on_net(name: str, type_: str) -> bool:
    if name == "goal":
        return True
    return name == "shot" and not type_.endswith("blocked")


def zone_entries(game: Game) -> dict[int, list[ZoneEntry]]:
    """
    Return all offensive zone entries per team for a game, computed from the
    compiled playsequence (build the Game with
    playsequence_source="playsequence_compiled").

    Each ZoneEntry records the entry type ("dumpin", "pass", or "carry"),
    the game time of entry, and every shot on net the entering team generated
    before the play left the zone, with the elapsed time from entry to shot.

    For dump-ins, `recovered` is True if the dumping team regained possession
    before the zone was exited, False otherwise. For pass and carry entries
    `recovered` is None.

    Returns a dict keyed by team_id with the two teams in the game.
    """
    events = sorted(game.events, key=lambda e: e.t)
    home_team_id = game.info.home_team.id
    away_team_id = game.info.away_team.id

    result: dict[int, list[ZoneEntry]] = {
        home_team_id: [],
        away_team_id: [],
    }

    current_entry: ZoneEntry | None = None
    checking_recovery: bool = False  # True while we still need to resolve a dumpin recovery

    for event in events:
        entry_type = _classify_entry(event)

        if entry_type is not None:
            team = event.team_id_in_possession or event.team_id
            if team is not None and team in result:
                team_sk = event.get_raw("team_skaters_on_ice")
                opp_sk = event.get_raw("opposing_team_skaters_on_ice")
                mps = ManpowerSituation(team_skaters=team_sk, opposing_team_skaters=opp_sk)
                shift_data = game.current_shift_toi(event.t)
                opposing_id = away_team_id if team == home_team_id else home_team_id
                current_entry = ZoneEntry(
                    team_id=team,
                    entry_type=entry_type,
                    entry_time=event.t,
                    recovered=False if entry_type == "dumpin" else None,
                    manpower_situation=mps,
                    team_shift_toi=shift_data.get(team, {}).get("total_team_shift_toi"),
                    opposing_team_shift_toi=shift_data.get(opposing_id, {}).get("total_team_shift_toi"),
                )
                result[team].append(current_entry)
                checking_recovery = entry_type == "dumpin"
            else:
                current_entry = None
                checking_recovery = False
            continue

        if current_entry is None:
            continue

        # Resolve dumpin recovery: first non-mirror event with a known possession
        if checking_recovery and event.name != "dumpinagainst":
            if event.team_id_in_possession is not None:
                current_entry.recovered = (event.team_id_in_possession == current_entry.team_id)
                checking_recovery = False

        if event.name in _ZONE_EXIT_NAMES:
            checking_recovery = False
            current_entry = None
            continue

        if _is_shot_on_net(event.name, event.type) and event.team_id == current_entry.team_id:
            current_entry.shots.append(
                ShotAfterEntry(time_since_entry=event.t - current_entry.entry_time)
            )
            if event.name == "goal":
                current_entry.goal = event.t - current_entry.entry_time

    return result


if __name__ == "__main__":
    import os
    from pathlib import Path

    from hockey.io.raw_game import RawGame
    from hockey.normalize.build_game import build_game

    GAME_ID = 191504

    root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
    raw = RawGame(GAME_ID, root_dir=root, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    print("(loaded from filesystem: playsequence_compiled)")

    entries = zone_entries(game)

    for team_id, team_entries in entries.items():
        team = game.info.home_team if game.info.home_team.id == team_id else game.info.away_team
        dumpins = [e for e in team_entries if e.entry_type == "dumpin"]
        recovered = [e for e in dumpins if e.recovered]

        print(f"{team.display_name}")
        print(f"  entries:  dumpin={len(dumpins)}  pass={sum(1 for e in team_entries if e.entry_type == 'pass')}  carry={sum(1 for e in team_entries if e.entry_type == 'carry')}")
        if dumpins:
            print(f"  dump-in recovery: {len(recovered)}/{len(dumpins)} ({len(recovered)/len(dumpins)*100:.0f}%)")
        for entry_type in ("dumpin", "pass", "carry"):
            es = [e for e in team_entries if e.entry_type == entry_type]
            shots = sum(e.shot_count for e in es)
            print(f"  shots from {entry_type}: {shots} across {len(es)} entries")
