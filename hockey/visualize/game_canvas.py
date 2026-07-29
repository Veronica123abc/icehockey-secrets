from __future__ import annotations

import json
import tempfile
import webbrowser
from collections import defaultdict
from pathlib import Path

import plotly.graph_objects as go

from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.model.events import Event
from hockey.model.game import Game
from hockey.normalize.build_game import build_game
from hockey.visualize.shift_toi import _game_end_time_seconds, _team_color

# Neutral fallback color for event lines with no (or unknown) possessing team.
_NEUTRAL_EVENT_COLOR = "#cbd5e1"

_DIV_ID = "timeline"


def _default_props(game: Game) -> dict:
    """Known style properties with defaults matching the existing dark theme."""
    home = game.info.home_team
    away = game.info.away_team
    return {
        "background-color": "#0f172a",
        "font-color": "#94a3b8",
        "title-color": "#e2e8f0",
        "axis-color": "#64748b",
        "grid-color": "#1e293b",
        "home-team-graph-color": _team_color(home.id, "#60a5fa"),
        "away-team-graph-color": _team_color(away.id, "#f87171"),
        "title": f"{home.display_name} vs {away.display_name}",
        "height": 750,
    }


class GameCanvas:
    """
    A generic, themed game-time timeline you can draw events onto.

    Renders a dark timeline (period bands, minute ticks, P1/P2/P3 labels) with
    a row of checkboxes underneath -- one per distinct event type that occurs
    in the game. All boxes start unchecked; toggling one shows/hides that
    event type's vertical lines on the timeline.

    ``draw_events`` optionally pre-selects (pre-checks) event types by passing
    a sample of events; by default nothing is checked.
    """

    def __init__(self, game: Game) -> None:
        self._game = game
        self._end_time = _game_end_time_seconds(game, default=3600)
        self._props = _default_props(game)
        # Distinct event types present in the game (assessed at construction).
        self._event_types: list[str] = sorted(
            {e.name for e in game.events if e.name and e.t is not None}
        )
        self._preselected: set[str] = set()
        # Precompute per-second shift-TOI snapshots once (avoids click-time lag).
        # Indexed by game second: self._toi_series[s] -> {team_id: {...}}.
        self._toi_series = game.shift_toi_series(range(self._end_time))

    def set_property(self, name: str, value) -> None:
        """Set a style property. Raises KeyError on an unknown property name."""
        if name not in self._props:
            raise KeyError(
                f"Unknown property {name!r}. Known: {sorted(self._props)}"
            )
        self._props[name] = value

    def draw_events(self, events: list[Event]) -> None:
        """Pre-select (pre-check) the event types present in ``events``."""
        self._preselected.update(
            e.name for e in events if e.name in set(self._event_types)
        )

    def show(self) -> None:
        """Render the visual on screen (opens in the browser)."""
        html = self._render_html()
        path = Path(tempfile.gettempdir()) / "game_canvas.html"
        path.write_text(html, encoding="utf-8")
        webbrowser.open(path.as_uri())

    # -- internals -----------------------------------------------------------

    def _period_time_str(self, t: float) -> str:
        """Format an absolute game time as 'Pn m.ss' (period-relative)."""
        current = round(t)
        period = current // 1200
        minutes = (current - period * 1200) // 60
        seconds = (current - period * 1200) % 60
        return f"P{period + 1} {minutes}.{seconds:02d}"

    def _event_color(self, event: Event) -> str:
        team = event.team_id_in_possession
        if team == self._game.info.home_team.id:
            return self._props["home-team-graph-color"]
        if team == self._game.info.away_team.id:
            return self._props["away-team-graph-color"]
        return _NEUTRAL_EVENT_COLOR

    def _build_figure(self) -> tuple[go.Figure, dict[str, list[int]]]:
        """
        Build the timeline figure plus a mapping of event type -> the trace
        indices that render it (so checkboxes can toggle them via restyle).
        """
        end_time = self._end_time
        props = self._props

        num_periods = max(3, (end_time + 1199) // 1200)
        tick_vals = list(range(0, end_time + 1, 300))
        tick_text = [str((t % 1200) // 60) for t in tick_vals]

        fig = go.Figure()

        # Period shading + dividers (always visible; not toggleable).
        shapes = []
        for p in range(num_periods):
            if p % 2 == 1:
                shapes.append(dict(
                    type="rect", xref="x", yref="paper",
                    x0=p * 1200, x1=min((p + 1) * 1200, end_time),
                    y0=0, y1=1,
                    fillcolor="rgba(255,255,255,0.04)",
                    line_width=0, layer="below",
                ))
        for p in range(1, num_periods):
            shapes.append(dict(
                type="line", xref="x", yref="paper",
                x0=p * 1200, x1=p * 1200,
                y0=0, y1=1,
                line=dict(color="#334155", width=1, dash="dot"),
            ))

        # One toggleable group of traces per event type. Events are drawn as
        # vertical line segments (x=[t,t,None], y=[0,1,None]); split by color
        # so possessing-team coloring is preserved within a type.
        events_by_type: dict[str, list[Event]] = defaultdict(list)
        for e in self._game.events:
            if e.name in self._event_types and e.t is not None:
                events_by_type[e.name].append(e)

        type_traces: dict[str, list[int]] = {}
        for etype in self._event_types:
            events = events_by_type[etype]
            visible = etype in self._preselected
            indices: list[int] = []

            by_color: dict[str, list[Event]] = defaultdict(list)
            for e in events:
                by_color[self._event_color(e)].append(e)

            for color, group in by_color.items():
                xs: list = []
                ys: list = []
                for e in group:
                    xs += [e.t, e.t, None]
                    ys += [0, 1, None]
                indices.append(len(fig.data))
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines",
                    line=dict(color=color, width=1),
                    name=etype,
                    hoverinfo="skip",
                    visible=visible,
                    showlegend=False,
                ))

            # Invisible mid-height markers give a large hover target so the
            # event's game time shows on hover (thin lines are hard to hit).
            indices.append(len(fig.data))
            fig.add_trace(go.Scatter(
                x=[e.t for e in events],
                y=[0.5] * len(events),
                mode="markers",
                marker=dict(size=16, opacity=0),
                name=etype,
                hovertext=[
                    f"{etype} — {self._period_time_str(e.t)}" for e in events
                ],
                hovertemplate="%{hovertext}<extra></extra>",
                visible=visible,
                showlegend=False,
            ))

            type_traces[etype] = indices

        period_annotations = [
            dict(
                x=(p + 0.5) * 1200, y=1.0, yref="paper",
                text=f"P{p + 1}" if p < 3 else "OT",
                showarrow=False,
                font=dict(color="#475569", size=14),
                xanchor="center", yanchor="bottom",
            )
            for p in range(num_periods)
        ]

        fig.update_layout(
            title=dict(
                text=props["title"],
                font=dict(color=props["title-color"], size=16),
            ),
            paper_bgcolor=props["background-color"],
            plot_bgcolor=props["background-color"],
            font=dict(color=props["font-color"], size=14),
            xaxis=dict(
                title=None,
                range=[0, end_time],
                tickvals=tick_vals,
                ticktext=tick_text,
                tickfont=dict(color=props["axis-color"], size=14),
                gridcolor=props["grid-color"],
                zerolinecolor="#334155",
                showline=False,
            ),
            yaxis=dict(
                range=[0, 1],
                showticklabels=False,
                showgrid=False,
                zeroline=False,
            ),
            shapes=shapes,
            annotations=period_annotations,
            height=props["height"],
            hovermode="closest",
            margin=dict(t=80, b=40, l=60, r=20),
        )
        return fig, type_traces

    def _player_name(self, player_id: int) -> str:
        p = self._game.roster.players.get(player_id)
        if p is None:
            return str(player_id)
        first = (p.first_name or "").strip()
        last = (p.last_name or "").strip()
        if first and last:
            return f"{first[0]}. {last}"
        return last or first or str(player_id)

    def _toi_embed(self) -> tuple[list[dict], dict[int, str]]:
        """
        Serialize the precomputed TOI series for the browser: a per-second
        list of {"h"/"a": {"avg", "players": [[player_id, toi], ...]}} plus a
        player-id -> display-name lookup.
        """
        home_id = self._game.info.home_team.id
        away_id = self._game.info.away_team.id
        names: dict[int, str] = {}
        data: list[dict] = []
        for snap in self._toi_series:
            rec = {}
            for key, tid in (("h", home_id), ("a", away_id)):
                team = snap.get(tid, {})
                players = []
                for pp in team.get("players", []):
                    pid = pp["player_id"]
                    names.setdefault(pid, self._player_name(pid))
                    players.append([pid, round(pp["current_shift_toi"])])
                players.sort(key=lambda z: -z[1])
                rec[key] = {
                    "avg": round(team.get("average_team_shift_toi", 0.0), 1),
                    "players": players,
                }
            data.append(rec)
        return data, names

    def _render_html(self) -> str:
        """Wrap the figure in an HTML page with per-event-type checkboxes."""
        fig, type_traces = self._build_figure()
        props = self._props

        fig_html = fig.to_html(
            full_html=False, include_plotlyjs="cdn", div_id=_DIV_ID
        )

        toi_data, toi_names = self._toi_embed()

        boxes = []
        for etype in self._event_types:
            checked = "checked" if etype in self._preselected else ""
            indices = json.dumps(type_traces[etype])
            boxes.append(
                f'<label class="evt">'
                f'<input type="checkbox" data-indices=\'{indices}\' '
                f'onchange="_toggle(this)" {checked}> {etype}</label>'
            )
        checkbox_html = "\n".join(boxes)

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background: {props['background-color']};
    color: {props['font-color']};
    font-family: sans-serif;
    margin: 0;
    padding: 16px;
  }}
  #controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 20px;
    padding: 12px 60px;
  }}
  .evt {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    user-select: none;
  }}
  #toi-box {{
    margin: 12px 60px 0;
    padding: 12px 16px;
    min-height: 120px;
    border: 1px solid {props['grid-color']};
    border-radius: 6px;
    background: rgba(255,255,255,0.02);
    font-family: ui-monospace, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
  }}
</style>
</head>
<body>
{fig_html}
<div id="controls">
{checkbox_html}
</div>
<pre id="toi-box">Click anywhere on the timeline to show current shift TOI.</pre>
<script>
var TOI_DATA = {json.dumps(toi_data)};
var TOI_NAMES = {json.dumps(toi_names)};
var HOME_NAME = {json.dumps(self._game.info.home_team.display_name)};
var AWAY_NAME = {json.dumps(self._game.info.away_team.display_name)};
var HOME_COLOR = {json.dumps(props['home-team-graph-color'])};
var AWAY_COLOR = {json.dumps(props['away-team-graph-color'])};

function _toggle(cb) {{
  var gd = document.getElementById('{_DIV_ID}');
  var indices = JSON.parse(cb.dataset.indices);
  if (indices.length) {{
    Plotly.restyle(gd, {{visible: cb.checked}}, indices);
  }}
}}

function _fmtTime(s) {{
  var p = Math.floor(s / 1200);
  var m = Math.floor((s - p * 1200) / 60);
  var ss = (s - p * 1200) % 60;
  return 'P' + (p + 1) + ' ' + m + '.' + (ss < 10 ? '0' : '') + ss;
}}

function _teamBlock(name, color, rec) {{
  var head = '<span style="color:' + color + '">' + name +
             '</span>  (avg ' + rec.avg + 's)';
  var lines = rec.players.map(function(pr) {{
    return '  ' + TOI_NAMES[pr[0]] + ': ' + pr[1] + 's';
  }}).join('\\n');
  return head + '\\n' + (lines || '  (no skaters on ice)');
}}

function _showToi(s) {{
  if (s < 0) s = 0;
  if (s >= TOI_DATA.length) s = TOI_DATA.length - 1;
  var rec = TOI_DATA[s];
  document.getElementById('toi-box').innerHTML =
    '<strong>' + _fmtTime(s) + '</strong>\\n\\n' +
    _teamBlock(HOME_NAME, HOME_COLOR, rec.h) + '\\n\\n' +
    _teamBlock(AWAY_NAME, AWAY_COLOR, rec.a);
}}

(function() {{
  var gd = document.getElementById('{_DIV_ID}');
  gd.addEventListener('click', function(evt) {{
    var fl = gd._fullLayout;
    if (!fl || !fl.xaxis) return;
    var xa = fl.xaxis;
    var bb = gd.getBoundingClientRect();
    var px = evt.clientX - bb.left - xa._offset;
    if (px < 0 || px > xa._length) return;  // ignore clicks in the margins
    var frac = px / xa._length;
    var x = xa.range[0] + frac * (xa.range[1] - xa.range[0]);
    _showToi(Math.round(x));
  }});
}})();
</script>
</body>
</html>
"""
GAME_ID = 202401
GAME_ID = 191504

if __name__ == "__main__":
    settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    game = build_game(raw)
    canvas = GameCanvas(game)
    canvas.set_property("title", "Timeline demo")
    canvas.show()
