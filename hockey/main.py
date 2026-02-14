from pathlib import Path
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.derive.on_ice import on_ice_at_events, strength_at_event
from hockey.visualize.shift_toi import plot_shift_toi_with_grades


raw = RawGame(game_id=168742, root_dir=Path("/home/veronica/hockeystats/ver3/"))
game = build_game(raw)



shots = [e for e in game.events if e.type == "shot"]
df_events = game.events_df()     # only builds DataFrame if you call it
df_raw = game.events_raw_df()


rows = on_ice_at_events(
    events=game.events,
    toi=game.toi,
    home_team_id=game.info.home_team.id,
    away_team_id=game.info.away_team.id,
    roster=game.roster,
    drop_goalies=True,
)
# for t in range(3600):
#
#     snapshot = game.current_shift_toi(float(t), reset_on_whistle=False)
#     snapshot_2 = game.current_shift_toi(float(t), reset_on_whistle=True)
#     print(snapshot == snapshot_2)
#snapshot = game.current_shift_toi(float(1000), reset_on_whistle=False)
fig = plot_shift_toi_with_grades(game=game, filename="toi_with_grades.html")
print(strength_at_event(rows[0]))