from __future__ import annotations

from collections.abc import Iterable

from hockey.model.events import Event


def _flags(event: Event) -> list[str]:
    return event.get_raw("flags") or []


def _is_slot(event: Event) -> bool:
    return event.type in ("slot", "slotblocked")


def _is_inner_slot(event: Event) -> bool:
    return _is_slot(event) and event.get_raw("play_section") == "innerSlot"


def _is_outside(event: Event) -> bool:
    return event.type in ("outside", "outsideblocked")


def _is_blocked(event: Event) -> bool:
    return event.type.endswith("blocked")


def _is_successful(event: Event) -> bool:
    return event.get_raw("outcome") == "successful"


def _is_missed(event: Event) -> bool:
    return not _is_blocked(event) and event.get_raw("outcome") == "failed"


def _is_deflected(event: Event) -> bool:
    return "deflected" in _flags(event)


def _is_1timer(event: Event) -> bool:
    return "1timer" in _flags(event)


def _is_regular_goal(event: Event) -> bool:
    return "withgoal" in _flags(event)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def shot_metrics(events: Iterable[Event]) -> dict[str, float]:
    """
    Compute all shooting metrics for the given events.

    Pre-filter `events` to the desired scope (team, player, etc.) before calling.
    Returns a dict mapping each metric name to its value.
    """
    shots = [e for e in events if e.name == "shot"]
    goals = [e for e in shots if _is_regular_goal(e)]

    slot_shots = [e for e in shots if _is_slot(e)]
    inner_slot_shots = [e for e in shots if _is_inner_slot(e)]
    outside_shots = [e for e in shots if _is_outside(e)]
    deflected_shots = [e for e in shots if _is_deflected(e)]

    slot_goals = [e for e in goals if _is_slot(e)]
    inner_slot_goals = [e for e in goals if _is_inner_slot(e)]
    outside_goals = [e for e in goals if _is_outside(e)]
    deflected_goal_events = [e for e in goals if _is_deflected(e)]

    # ── Slot ──────────────────────────────────────────────────────────
    slot_successful = sum(1 for e in slot_shots if _is_successful(e))
    slot_blocked    = sum(1 for e in slot_shots if _is_blocked(e))
    slot_missed     = sum(1 for e in slot_shots if _is_missed(e))
    slot_total      = len(slot_shots)
    slot_1timers    = sum(1 for e in slot_shots if _is_1timer(e))

    # ── Deflected ──────────────────────────────────────────────────────
    defl_successful = sum(1 for e in deflected_shots if _is_successful(e))
    defl_blocked    = sum(1 for e in deflected_shots if _is_blocked(e))
    defl_missed     = sum(1 for e in deflected_shots if _is_missed(e))
    defl_total      = len(deflected_shots)

    # ── Inner slot ────────────────────────────────────────────────────
    inner_successful = sum(1 for e in inner_slot_shots if _is_successful(e))
    inner_1timers    = sum(1 for e in inner_slot_shots if _is_1timer(e))

    # ── Outside ───────────────────────────────────────────────────────
    out_successful = sum(1 for e in outside_shots if _is_successful(e))
    out_blocked    = sum(1 for e in outside_shots if _is_blocked(e))
    out_missed     = sum(1 for e in outside_shots if _is_missed(e))
    out_total      = len(outside_shots)
    out_1timers    = sum(1 for e in outside_shots if _is_1timer(e))

    # ── Total ──────────────────────────────────────────────────────────
    total_shots      = len(shots)
    total_successful = sum(1 for e in shots if _is_successful(e))
    total_blocked    = sum(1 for e in shots if _is_blocked(e))
    total_missed     = sum(1 for e in shots if _is_missed(e))
    total_1timers    = sum(1 for e in shots if _is_1timer(e))
    total_goals      = len(goals)

    return {
        "Total Successful Shot From Slot Attempts":    slot_successful,
        "Failed Shot From Slot Attempts - Blocked":    slot_blocked,
        "Failed Shot From Slot Attempts - Missed":     slot_missed,
        "Total Shot From Slot Attempts":               slot_total,
        "1 Timers Shot from Slot":                     slot_1timers,
        "Total Regular Goals From Slot":               len(slot_goals),
        "Total Successful Deflected Shot Attempts":    defl_successful,
        "Failed Deflected Shot Attempts - Blocked":    defl_blocked,
        "Failed Deflected Shot Attempts - Missed":     defl_missed,
        "Total Deflected Shot Attempts":               defl_total,
        "Total Regular Goals From Deflected Shots":    len(deflected_goal_events),
        "Total Successful Shots Taken From Inner Slot": inner_successful,
        "1 Timers Shot from Inner Slot":               inner_1timers,
        "Total Regular Goals From Inner Slot":         len(inner_slot_goals),
        "Total Successful Outside Shot Attempts":      out_successful,
        "Failed Outside Shot Attempts - Blocked":      out_blocked,
        "Failed Outside Shot Attempts - Missed":       out_missed,
        "Total Outside Shot Attempts":                 out_total,
        "1 Timers Shot from Outside Slot":             out_1timers,
        "Total Regular Goals From Outside Slot":       len(outside_goals),
        "Total Shots Taken":                           total_shots,
        "Total Successful Shots Taken":                total_successful,
        "Failed Shots Taken - Blocked":                total_blocked,
        "Failed Shots Taken - Missed":                 total_missed,
        "1 Timers Shot":                               total_1timers,
        "Total Regular Goals":                         total_goals,
        "Shots From Slot Success Rate":                _rate(slot_successful, slot_total),
        "1 Timers Shot% from Slot":                    _rate(slot_1timers, slot_total),
        "Deflected Shots Success Rate":                _rate(defl_successful, defl_total),
        "1 Timers Shot% from Inner Slot":              _rate(inner_1timers, len(inner_slot_shots)),
        "Outside Shots Success Rate":                  _rate(out_successful, out_total),
        "1 Timers Shot% from Outside Slot":            _rate(out_1timers, out_total),
        "Shots From Slot Percentage":                  _rate(slot_total, total_shots),
        "Total Shots Success Rate":                    _rate(total_successful, total_shots),
        "1 Timers Shot% Total":                        _rate(total_1timers, total_shots),
    }


if __name__ == "__main__":
    import os
    from pathlib import Path

    GAME_ID = 143062

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

    for team in (game.info.home_team, game.info.away_team):
        team_events = [e for e in game.events if e.team_id == team.id]
        metrics = shot_metrics(team_events)
        print(f"\n{team.display_name}")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
