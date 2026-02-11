from pathlib import Path
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.derive.on_ice import on_ice_at_events, strength_at_event

raw = RawGame(game_id=168742, root_dir=Path("/home/veronica/hockeystats/ver3/"))
game = build_game(raw)

shots = [e for e in game.events if e.type == "shot"]
df_events = game.events_df()     # only builds DataFrame if you call it



rows = on_ice_at_events(
    events=game.events,
    toi=game.toi,
    home_team_id=game.info.home_team.id,
    away_team_id=game.info.away_team.id,
    drop_goalies=True,
)
snapshot = game.current_shift_toi(1234.5)
print(strength_at_event(rows[0]))