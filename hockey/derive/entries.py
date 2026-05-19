from __future__ import annotations

from dataclasses import dataclass, field

from hockey.model.game import Game


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

    @property
    def shot_count(self) -> int:
        return len(self.shots)


_PASS_OZ_TYPES = frozenset({"ozentry", "ozentryoffboards", "ozentrystretchoffboards"})


def _classify_entry(event) -> str | None:
    name = event.name
    if name == "carry" and event.get_raw("zone") == "oz" and event.get_raw("outcome") == "successful":
        return "carry"
    if name == "dumpin" and event.get_raw("outcome") == "successful":
        return "dumpin"
    if name == "pass" and event.type in _PASS_OZ_TYPES:
        return "pass"
    return None

# Events that end the current zone possession
_ZONE_EXIT_NAMES = frozenset({"whistle", "icing", "offside", "dumpout", "controlledbreakout"})


def _is_shot_on_net(name: str, type_: str) -> bool:
    if name == "goal":
        return True
    return name == "shot" and not type_.endswith("blocked")


def zone_entries(game: Game) -> dict[int, list[ZoneEntry]]:
    """
    Return all offensive zone entries per team for a game.

    Each ZoneEntry records the entry type ("dumpin", "pass", or "carry"),
    the game time of entry, and every shot on net the entering team generated
    before the play left the zone, with the elapsed time from entry to shot.

    For dump-ins, `recovered` is True if the dumping team regained possession
    before the zone was exited, False otherwise. For pass and carry entries
    `recovered` is None.

    Returns a dict keyed by team_id with the two teams in the game.
    """
    events = sorted(game.events, key=lambda e: e.t)

    result: dict[int, list[ZoneEntry]] = {
        game.info.home_team.id: [],
        game.info.away_team.id: [],
    }

    current_entry: ZoneEntry | None = None
    checking_recovery: bool = False  # True while we still need to resolve a dumpin recovery

    for event in events:
        entry_type = _classify_entry(event)

        if entry_type is not None:
            team = event.team_id_in_possession or event.team_id
            if team is not None and team in result:
                current_entry = ZoneEntry(
                    team_id=team,
                    entry_type=entry_type,
                    entry_time=event.t,
                    recovered=False if entry_type == "dumpin" else None,
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

    return result


if __name__ == "__main__":
    import os
    from pathlib import Path

    GAME_ID = 54559

    game = None
    host = os.getenv("DATABASE_HOST_AZURE")
    if host:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=host,
                user=os.environ["DATABASE_USERNAME_AZURE"],
                password=os.environ["DATABASE_PWD_AZURE"],
                database=os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
                auth_plugin="mysql_native_password",
            )
            from hockey.normalize.build_game_db import build_game_from_db
            game = build_game_from_db(GAME_ID, conn)
            conn.close()
            print("(loaded from database)")
        except Exception as e:
            print(f"(DB load failed: {e}, falling back to filesystem)")

    if game is None:
        from hockey.io.raw_game import RawGame
        from hockey.normalize.build_game import build_game
        root = Path(os.getenv("DATA_ROOT_DIR", "/home/veronica/hockeystats/ver3"))
        raw = RawGame(game_id=GAME_ID, root_dir=root)
        game = build_game(raw)
        print("(loaded from filesystem)")
    entries = zone_entries(game)

    for team_id, team_entries in entries.items():
        team = game.info.home_team if game.info.home_team.id == team_id else game.info.away_team
        dumpins = [e for e in team_entries if e.entry_type == "dumpin"]
        recovered = [e for e in dumpins if e.recovered]

        print(f"{team.display_name}")
        print(f"  entries:  dumpin={len(dumpins)}  pass={sum(1 for e in team_entries if e.entry_type == 'pass')}  carry={sum(1 for e in team_entries if e.entry_type == 'carry')}")
        print(f"  dump-in recovery: {len(recovered)}/{len(dumpins)} ({len(recovered)/len(dumpins)*100:.0f}%)")
        for entry_type in ("dumpin", "pass", "carry"):
            es = [e for e in team_entries if e.entry_type == entry_type]
            shots = sum(e.shot_count for e in es)
            print(f"  shots from {entry_type}: {shots} across {len(es)} entries")
        print("apa")
