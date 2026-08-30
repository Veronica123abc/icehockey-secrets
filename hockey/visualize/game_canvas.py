from __future__ import annotations

import json
import tempfile
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
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
    """Known style properties, defaulting to the app palette (templates/base.html)."""
    home = game.info.home_team
    away = game.info.away_team
    return {
        "background-color": "#0f172a",   # page
        "card-color": "#1e293b",         # panels the content sits in
        "border-color": "#334155",       # panel borders, dividers
        "font-color": "#94a3b8",         # muted / secondary text
        "text-color": "#e2e8f0",         # body text
        "title-color": "#f8fafc",        # headings, team names, score
        "axis-color": "#64748b",         # axis labels, captions
        "grid-color": "rgba(148, 163, 184, 0.08)",
        "home-team-graph-color": _team_color(home.id, "#60a5fa"),
        "away-team-graph-color": _team_color(away.id, "#f87171"),
        # The teams and score are carried by the scoreboard band, so this is
        # just the label above the chart.
        "title": "Timeline",
        # None = size the chart to however many lanes are showing. Set an int
        # to pin it instead.
        "height": None,
        "lane-height": 36,
    }


_STAGE_LABELS = {"regular": "Regular season", "playoff": "Playoffs"}

# Display grouping for the event-type rail. A game has ~40 distinct types,
# which is too many for one flat list. Order within a group is deliberate
# (most-used first), not alphabetical. Types absent from this table fall into
# a trailing "Other" group, so a game from another league still lists all of
# its types.
_EVENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Scoring", (
        "goal", "goalagainst", "assist", "scoringchance", "shot",
        "loosepuckshot", "rebound", "save", "block",
    )),
    ("Entries & exits", (
        "controlledentry", "controlledentryagainst", "dumpin", "dumpinentry",
        "dumpinagainst", "dumpinrecovery", "zoneexit", "controlledexit",
        "dumpout", "dumpoutrecovery", "breakout", "controlledbreakout",
        "carrytoslot", "endtoendrush",
    )),
    ("Puck movement", (
        "possession", "pass", "reception", "lpr", "carry", "puckprotection",
        "failedpasslocation", "receptionprevention", "innerslotclear",
    )),
    ("Pressure & physical", ("check", "pressure")),
    ("Stoppages & specials", (
        "faceoff", "faceoffrecovery", "penalty", "penaltydrawn", "icing",
        "offside", "goalieloss", "goaliewin",
    )),
)

_OTHER_GROUP = "Other"

# Ticking a type this common draws a wall of lines rather than a signal; the
# count is flagged so you can see that before you tick it.
_DENSE_THRESHOLD = 300

# Lane geometry. A lane is one y unit; ticks fill the middle 70% of it.
_LANE_HALF = 0.35
# Vertical space the chart needs besides the lanes themselves (the x axis and
# the top/bottom margins), used when sizing the chart to its lane count.
_LANE_CHROME = 54
# Floor for the lane area. One lane's worth of plot is a sliver that's awkward
# to click for a TOI readout, so short selections still get a usable strip.
_MIN_LANE_AREA = 96


def _lane_margin(lanes: list[str]) -> int:
    """Left margin wide enough for the longest visible lane label."""
    if not lanes:
        return 12
    return min(220, max(60, max(len(name) for name in lanes) * 7 + 16))


_SANS = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, '
         'Arial, sans-serif')
_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


class GameCanvas:
    """
    A generic, themed game-time timeline you can draw events onto.

    Renders a dark timeline (period bands, minute ticks, P1/P2/P3 labels) in a
    card, with a scoreboard band above it and a rail of checkboxes beside it --
    one per distinct event type that occurs in the game. All boxes start
    unchecked; ticking one gives that type its own lane on the timeline, so
    types stay separable rather than overprinting each other. Lanes are packed
    in the rail's reading order and reflow as types are toggled. Clicking the
    timeline parks a playhead and reads out current shift TOI below it.

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
        # Rail reading order, which is also the order lanes are packed in.
        self._display_order: list[str] = [
            name for _, names in self._group_event_types() for name in names
        ]
        # How many events of each type -- shown in the rail so the cost of
        # ticking a type is visible before you tick it.
        self._event_counts: Counter[str] = Counter(
            e.name for e in game.events if e.name and e.t is not None
        )
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

    def _initial_lanes(self) -> list[str]:
        """Types that start with a lane, in the rail's reading order."""
        return [t for t in self._display_order if t in self._preselected]

    def _chart_height(self, num_lanes: int) -> int:
        """Chart height for a lane count, unless ``height`` was set explicitly."""
        if self._props["height"] is not None:
            return self._props["height"]
        return _LANE_CHROME + max(
            _MIN_LANE_AREA, num_lanes * self._props["lane-height"]
        )

    def _event_color(self, event: Event) -> str:
        # Colour by the acting team. team_id is populated on every event;
        # team_id_in_possession is null on ~40% of them (all scoring chances,
        # entries and faceoffs), which would paint most ticks neutral grey.
        team = event.team_id if event.team_id is not None else event.team_id_in_possession
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
                    fillcolor="rgba(148, 163, 184, 0.05)",
                    line_width=0, layer="below",
                ))
        for p in range(1, num_periods):
            shapes.append(dict(
                type="line", xref="x", yref="paper",
                x0=p * 1200, x1=p * 1200,
                y0=0, y1=1,
                line=dict(color=props["border-color"], width=1, dash="dot"),
            ))

        # One toggleable group of traces per event type. Events are drawn as
        # vertical line segments (x=[t,t,None], y=[0,1,None]); split by color
        # so possessing-team coloring is preserved within a type.
        events_by_type: dict[str, list[Event]] = defaultdict(list)
        for e in self._game.events:
            if e.name in self._event_types and e.t is not None:
                events_by_type[e.name].append(e)

        # Lanes: each visible type occupies one row of the y axis, so types
        # stay separable instead of overprinting each other. Lanes are packed
        # (no gaps) in display order, which means toggling a type off reflows
        # the ones below it -- the browser redoes this in _relayoutLanes().
        lanes = self._initial_lanes()
        lane_of = {etype: i for i, etype in enumerate(lanes)}

        type_traces: dict[str, list[int]] = {}
        lane_specs: dict[str, list[list]] = {}
        for etype in self._display_order:
            events = events_by_type[etype]
            visible = etype in self._preselected
            lane = lane_of.get(etype, 0)
            low, high = lane - _LANE_HALF, lane + _LANE_HALF
            specs: list[list] = []

            by_color: dict[str, list[Event]] = defaultdict(list)
            for e in events:
                by_color[self._event_color(e)].append(e)

            for color, group in by_color.items():
                xs: list = []
                ys: list = []
                for e in group:
                    xs += [e.t, e.t, None]
                    ys += [low, high, None]
                specs.append([len(fig.data), "line", len(group)])
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines",
                    line=dict(color=color, width=1),
                    name=etype,
                    hoverinfo="skip",
                    visible=visible,
                    showlegend=False,
                ))

            # Invisible on-lane markers give a large hover target so the
            # event's game time shows on hover (thin lines are hard to hit).
            specs.append([len(fig.data), "hover", len(events)])
            fig.add_trace(go.Scatter(
                x=[e.t for e in events],
                y=[lane] * len(events),
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

            lane_specs[etype] = specs
            type_traces[etype] = [s[0] for s in specs]

        self._lane_specs = lane_specs

        period_annotations = [
            dict(
                x=(p + 0.5) * 1200, y=1.0, yref="paper",
                text=f"P{p + 1}" if p < 3 else "OT",
                showarrow=False,
                font=dict(color=props["axis-color"], size=12),
                xanchor="center", yanchor="bottom",
            )
            for p in range(num_periods)
        ]

        # Playhead: a click parks this line at the clicked time. Both pieces
        # live in the layout from the start (hidden), so a click is one
        # relayout of two indices rather than a rebuild of the whole list.
        self._playhead_shape = len(shapes)
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=0, x1=0, y0=0, y1=1,
            line=dict(color="rgba(248, 250, 252, 0.55)", width=1),
            visible=False,
        ))
        self._playhead_note = len(period_annotations)
        period_annotations.append(dict(
            x=0, y=1.0, yref="paper", text="",
            showarrow=False,
            font=dict(color=props["background-color"], size=11),
            bgcolor=props["text-color"], borderpad=3,
            xanchor="center", yanchor="bottom",
            visible=False,
        ))

        fig.update_layout(
            # Transparent so the card behind the chart shows through.
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=props["font-color"], size=12),
            xaxis=dict(
                title=None,
                range=[0, end_time],
                tickvals=tick_vals,
                ticktext=tick_text,
                tickfont=dict(color=props["axis-color"], size=11),
                gridcolor=props["grid-color"],
                zerolinecolor=props["border-color"],
                showline=False,
            ),
            yaxis=dict(
                # Descending range puts the first lane at the top.
                range=[len(lanes) - 0.5, -0.5] if lanes else [0, 1],
                tickvals=list(range(len(lanes))),
                ticktext=lanes,
                showticklabels=bool(lanes),
                tickfont=dict(color=props["text-color"], size=12),
                ticks="",
                showgrid=False,
                zeroline=False,
            ),
            shapes=shapes,
            annotations=period_annotations,
            height=self._chart_height(len(lanes)),
            hovermode="closest",
            margin=dict(t=26, b=28, l=_lane_margin(lanes), r=12),
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

    def _player_position(self, player_id: int) -> str:
        p = self._game.roster.players.get(player_id)
        return (p.position or "") if p is not None else ""

    def _toi_bar_ceiling(self) -> int:
        """Shared upper bound for the TOI bars, in seconds.

        The 90th percentile rounded up to 10s (floor 40s). Scaling to the
        longest shift in the game would squash every normal one into a stub --
        in 191504 the max is 175s against a 25s median. The top decile clamps
        at a full bar; the number beside it still reads true.
        """
        values = sorted(
            round(pp["current_shift_toi"])
            for snap in self._toi_series
            for team in snap.values()
            for pp in team.get("players", [])
        )
        if not values:
            return 40
        p90 = values[min(len(values) - 1, int(len(values) * 0.90))]
        return max(40, -(-p90 // 10) * 10)

    def _toi_embed(self) -> tuple[list[dict], dict[int, str], dict[int, str]]:
        """
        Serialize the precomputed TOI series for the browser: a per-second
        list of {"h"/"a": {"avg", "players": [[player_id, toi], ...]}} plus
        player-id -> display-name and player-id -> position lookups.
        """
        home_id = self._game.info.home_team.id
        away_id = self._game.info.away_team.id
        names: dict[int, str] = {}
        positions: dict[int, str] = {}
        data: list[dict] = []
        for snap in self._toi_series:
            rec = {}
            for key, tid in (("h", home_id), ("a", away_id)):
                team = snap.get(tid, {})
                players = []
                for pp in team.get("players", []):
                    pid = pp["player_id"]
                    # Escaped here: the panel writes these with innerHTML.
                    names.setdefault(pid, escape(self._player_name(pid)))
                    positions.setdefault(pid, escape(self._player_position(pid)))
                    players.append([pid, round(pp["current_shift_toi"])])
                players.sort(key=lambda z: -z[1])
                rec[key] = {
                    "avg": round(team.get("average_team_shift_toi", 0.0), 1),
                    "players": players,
                }
            data.append(rec)
        return data, names, positions

    def _format_date(self, iso: str) -> str:
        try:
            return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
        except (TypeError, ValueError):
            return iso

    def _scoreboard_html(self) -> str:
        """The identity band: teams, score and game metadata."""
        props = self._props
        info = self._game.info

        if info.home_final_score is not None and info.away_final_score is not None:
            score = (f'<span class="score">{info.home_final_score}'
                     f'<span class="dash"> – </span>{info.away_final_score}</span>')
        else:
            score = '<span class="vs">vs</span>'

        meta = []
        if info.date:
            meta.append(self._format_date(info.date))
        if info.stage:
            meta.append(_STAGE_LABELS.get(info.stage, info.stage.capitalize()))
        meta.append(f"Game {info.game_id}")

        return f"""<div class="scoreboard">
  <span class="team"><i class="dot" style="background: {props['home-team-graph-color']}"></i>{info.home_team.display_name}</span>
  {score}
  <span class="team"><i class="dot" style="background: {props['away-team-graph-color']}"></i>{info.away_team.display_name}</span>
  <span class="sep"></span>
  <span class="meta">{' · '.join(meta)}</span>
  <span class="spacer"></span>
  <span class="counts">{len(self._game.events):,} events · {len(self._event_types)} types</span>
</div>"""

    def _legend_html(self) -> str:
        props = self._props
        items = (
            (props["home-team-graph-color"], self._game.info.home_team.display_name),
            (props["away-team-graph-color"], self._game.info.away_team.display_name),
            (_NEUTRAL_EVENT_COLOR, "unattributed"),
        )
        return "".join(
            f'<span><i style="background: {color}"></i>{label}</span>'
            for color, label in items
        )

    def _group_event_types(self) -> list[tuple[str, list[str]]]:
        """Bucket this game's event types into display groups, in a fixed order.

        Only groups with at least one type present in this game are returned;
        anything not covered by ``_EVENT_GROUPS`` lands in a trailing "Other".
        """
        remaining = set(self._event_types)
        groups: list[tuple[str, list[str]]] = []
        for title, names in _EVENT_GROUPS:
            present = [n for n in names if n in remaining]
            if present:
                remaining.difference_update(present)
                groups.append((title, present))
        if remaining:
            groups.append((_OTHER_GROUP, sorted(remaining)))
        return groups

    def _rail_html(self, type_traces: dict[str, list[int]]) -> str:
        """The event-type rail: collapsible groups of checkboxes with counts.

        A group starts expanded only if it contains a pre-selected type, so an
        untouched canvas opens as a short menu rather than a 40-row list.
        """
        blocks = []
        for title, names in self._group_event_types():
            on = sum(1 for n in names if n in self._preselected)
            rows = []
            for name in names:
                count = self._event_counts[name]
                checked = " checked" if name in self._preselected else ""
                dense = " dense" if count >= _DENSE_THRESHOLD else ""
                indices = json.dumps(type_traces[name])
                rows.append(
                    f'        <label class="evt" data-type="{name}">'
                    f'<input type="checkbox" data-indices=\'{indices}\''
                    f' onchange="_toggle(this)"{checked}>'
                    f'<span class="evt-name">{name}</span>'
                    f'<span class="evt-count{dense}">{count:,}</span></label>'
                )
            badge = (f'<span class="badge">{on} on</span>' if on
                     else '<span class="badge" hidden></span>')
            body_hidden = "" if on else " hidden"
            blocks.append(f"""      <div class="group{' open' if on else ''}">
        <div class="group-head" onclick="_toggleGroup(this)">
          <svg class="chev" width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M6 4 L10 8 L6 12" stroke="{self._props['axis-color']}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="group-name">{title}</span>
          <span class="group-size">{len(names)}</span>
          <span class="spacer"></span>{badge}
        </div>
        <div class="group-body"{body_hidden}>
{chr(10).join(rows)}
        </div>
      </div>""")
        return "\n".join(blocks)

    def _render_html(self) -> str:
        """Wrap the figure in an HTML page with per-event-type checkboxes."""
        fig, type_traces = self._build_figure()
        props = self._props

        fig_html = fig.to_html(
            full_html=False, include_plotlyjs="cdn", div_id=_DIV_ID
        )

        toi_data, toi_names, toi_positions = self._toi_embed()
        toi_ceiling = self._toi_bar_ceiling()

        rail_html = self._rail_html(type_traces)

        num_types = len(self._event_types)
        selected = len(self._preselected)
        rail_meta = (f"{num_types} types in this game · "
                     + (f"{selected} on chart" if selected else "none on chart"))

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{props['title']} — {self._game.info.home_team.display_name} vs {self._game.info.away_team.display_name}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    background: {props['background-color']};
    color: {props['text-color']};
    font-family: {_SANS};
    margin: 0;
  }}
  .scoreboard {{
    display: flex;
    align-items: center;
    gap: 18px;
    height: 72px;
    padding: 0 24px;
    background: {props['card-color']};
    border-bottom: 1px solid {props['border-color']};
  }}
  .team {{
    display: inline-flex;
    align-items: center;
    gap: 9px;
    font-size: 15px;
    font-weight: 600;
    color: {props['title-color']};
  }}
  .dot {{ width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }}
  .score {{
    font-size: 21px;
    font-weight: 700;
    color: {props['title-color']};
    font-variant-numeric: tabular-nums;
  }}
  .score .dash {{ color: #475569; font-weight: 400; }}
  .vs {{ font-size: 14px; color: {props['font-color']}; }}
  .sep {{ width: 1px; height: 26px; background: {props['border-color']}; }}
  .meta {{ font-size: 12.5px; color: {props['font-color']}; }}
  .spacer {{ flex-grow: 1; }}
  .counts {{
    font-size: 12.5px;
    color: {props['axis-color']};
    font-variant-numeric: tabular-nums;
  }}
  .layout {{
    display: flex;
    align-items: flex-start;
    gap: 20px;
    padding: 20px 24px 24px;
  }}
  .card {{
    background: {props['card-color']};
    border: 1px solid {props['border-color']};
    border-radius: 8px;
  }}
  .rail {{
    width: 320px;
    flex-shrink: 0;
    padding: 16px;
    max-height: calc(100vh - 132px);
    overflow-y: auto;
  }}
  .main {{ flex-grow: 1; min-width: 0; }}
  .section-heading {{
    font-size: 12px;
    font-weight: 600;
    color: {props['font-color']};
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  .rail-meta {{
    font-size: 11.5px;
    color: {props['axis-color']};
    margin: 5px 0 10px;
  }}
  [hidden] {{ display: none !important; }}
  .rail-head {{ display: flex; align-items: center; height: 20px; }}
  .clear {{
    font-family: inherit;
    font-size: 12px;
    color: {props['home-team-graph-color']};
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
  }}
  .clear:hover {{ text-decoration: underline; }}
  .search {{
    display: flex;
    align-items: center;
    gap: 8px;
    height: 34px;
    padding: 0 10px;
    margin: 13px 0 6px;
    background: {props['background-color']};
    border: 1px solid {props['border-color']};
    border-radius: 6px;
  }}
  .search svg {{ flex-shrink: 0; }}
  .search input {{
    flex-grow: 1;
    min-width: 0;
    background: none;
    border: 0;
    outline: none;
    font-family: inherit;
    font-size: 12.5px;
    color: {props['text-color']};
  }}
  .search input::placeholder {{ color: {props['axis-color']}; }}
  #controls {{ display: flex; flex-direction: column; }}
  .group-head {{
    display: flex;
    align-items: center;
    gap: 7px;
    height: 32px;
    cursor: pointer;
    user-select: none;
  }}
  .group-name {{ font-size: 12.5px; font-weight: 600; color: #cbd5e1; }}
  .group-size {{ font-size: 11px; color: {props['axis-color']}; }}
  .chev {{ flex-shrink: 0; transition: transform 120ms ease; }}
  .group.open .chev {{ transform: rotate(90deg); }}
  .badge {{
    font-size: 10.5px;
    font-weight: 600;
    color: #93bbfd;
    background: rgba(96, 165, 250, 0.16);
    border-radius: 9999px;
    padding: 1.5px 7px;
  }}
  .group-body {{
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-bottom: 8px;
  }}
  .evt {{
    display: flex;
    align-items: center;
    gap: 9px;
    height: 28px;
    padding: 0 8px;
    margin: 0 -8px;
    border-radius: 5px;
    font-size: 12.5px;
    color: {props['font-color']};
    cursor: pointer;
    user-select: none;
  }}
  .evt:hover {{
    background: rgba(148, 163, 184, 0.08);
    color: {props['text-color']};
  }}
  .evt:has(input:checked) {{ background: rgba(96, 165, 250, 0.09); }}
  .evt:has(input:checked) .evt-name {{ color: {props['text-color']}; }}
  .evt input {{
    width: 14px;
    height: 14px;
    margin: 0;
    flex-shrink: 0;
    accent-color: {props['home-team-graph-color']};
    cursor: pointer;
  }}
  .evt-name {{ flex-grow: 1; min-width: 0; }}
  .evt-count {{
    font-size: 11px;
    color: {props['axis-color']};
    font-variant-numeric: tabular-nums;
  }}
  .evt-count.dense {{ color: #fbbf24; }}
  .timeline-card {{ padding: 18px 20px 14px; }}
  .card-head {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 4px;
  }}
  .legend {{ display: flex; align-items: center; gap: 14px; margin-left: auto; }}
  .legend span {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: {props['font-color']};
  }}
  .legend i {{ width: 8px; height: 8px; border-radius: 2px; display: block; }}
  .toi-card {{ padding: 18px 20px; margin-top: 20px; }}
  .toi-head {{ display: flex; align-items: center; gap: 12px; }}
  .time-chip {{
    font-size: 12px;
    color: {props['text-color']};
    background: {props['border-color']};
    border-radius: 4px;
    padding: 3px 8px;
    font-variant-numeric: tabular-nums;
  }}
  .toi-hint {{ font-size: 11.5px; color: {props['axis-color']}; }}
  #toi-box {{ margin-top: 14px; min-height: 112px; }}
  .toi-empty {{
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 92px;
    font-size: 12.5px;
    color: {props['axis-color']};
  }}
  .toi-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 28px;
  }}
  .toi-team-head {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 9px;
    margin-bottom: 6px;
    border-bottom: 1px solid {props['border-color']};
  }}
  .toi-team-name {{ font-size: 13px; font-weight: 600; color: {props['title-color']}; }}
  .toi-avg {{ font-size: 12px; color: {props['font-color']}; }}
  .toi-avg b {{ color: {props['text-color']}; font-family: {_MONO}; font-weight: 600; }}
  .toi-row {{ display: flex; align-items: center; gap: 10px; height: 29px; }}
  .toi-row .pos {{
    width: 26px;
    flex-shrink: 0;
    font-size: 10.5px;
    font-weight: 600;
    color: {props['axis-color']};
  }}
  .toi-row .pname {{
    flex-grow: 1;
    min-width: 0;
    font-size: 12.5px;
    color: {props['text-color']};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .toi-row .bar {{
    position: relative;
    width: 128px;
    height: 6px;
    flex-shrink: 0;
    border-radius: 3px;
    background: {props['background-color']};
  }}
  .toi-row .bar i {{
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    display: block;
    border-radius: 3px;
  }}
  .toi-row .secs {{
    width: 34px;
    flex-shrink: 0;
    text-align: right;
    font-family: {_MONO};
    font-size: 12px;
    color: #cbd5e1;
  }}
  .toi-none {{ font-size: 12.5px; color: {props['axis-color']}; padding: 6px 0; }}
</style>
</head>
<body>
{self._scoreboard_html()}
<div class="layout">
  <div class="card rail">
    <div class="rail-head">
      <span class="section-heading">Event types</span>
      <span class="spacer"></span>
      <button type="button" class="clear" onclick="_clearAll()">Clear</button>
    </div>
    <div class="rail-meta" id="rail-meta">{rail_meta}</div>
    <div class="search">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4.4" stroke="{props['axis-color']}" stroke-width="1.5"/><path d="M10.4 10.4 L14 14" stroke="{props['axis-color']}" stroke-width="1.5" stroke-linecap="round"/></svg>
      <input type="text" id="type-filter" placeholder="Filter types…" autocomplete="off" oninput="_filter(this.value)">
    </div>
    <div id="controls">
{rail_html}
    </div>
    <div class="rail-meta" id="no-match" hidden>No types match that filter.</div>
  </div>
  <div class="main">
    <div class="card timeline-card">
      <div class="card-head">
        <span class="section-heading">{props['title']}</span>
        <span class="legend">{self._legend_html()}</span>
      </div>
{fig_html}
    </div>
    <div class="card toi-card">
      <div class="toi-head">
        <span class="section-heading">Current shift TOI</span>
        <span class="time-chip" id="toi-time" hidden></span>
        <span class="spacer"></span>
        <span class="toi-hint">click the timeline to move the playhead</span>
      </div>
      <div id="toi-box"><div class="toi-empty">Click anywhere on the timeline to read current shift TOI at that moment.</div></div>
    </div>
  </div>
</div>
<script>
var TOI_DATA = {json.dumps(toi_data)};
var TOI_NAMES = {json.dumps(toi_names)};
var TOI_POS = {json.dumps(toi_positions)};
var TOI_CEIL = {toi_ceiling};
var PLAYHEAD_SHAPE = {self._playhead_shape};
var PLAYHEAD_NOTE = {self._playhead_note};
var LANE_ORDER = {json.dumps(self._display_order)};
var LANE_SPECS = {json.dumps(self._lane_specs)};
var LANE_HALF = {_LANE_HALF};
var LANE_HEIGHT = {props['lane-height']};
var LANE_CHROME = {_LANE_CHROME};
var MIN_LANE_AREA = {_MIN_LANE_AREA};
var HEIGHT_AUTO = {json.dumps(props['height'] is None)};
var HOME_NAME = {json.dumps(self._game.info.home_team.display_name)};
var AWAY_NAME = {json.dumps(self._game.info.away_team.display_name)};
var HOME_COLOR = {json.dumps(props['home-team-graph-color'])};
var AWAY_COLOR = {json.dumps(props['away-team-graph-color'])};
var NUM_TYPES = {num_types};
var _preSearchOpen = null;   // group open/closed state to restore after a search

function _toggle(cb) {{
  var gd = document.getElementById('{_DIV_ID}');
  var indices = JSON.parse(cb.dataset.indices);
  if (indices.length) {{
    Plotly.restyle(gd, {{visible: cb.checked}}, indices);
  }}
  _relayoutLanes();
  _updateCounts();
}}

function _visibleTypes() {{
  return LANE_ORDER.filter(function(t) {{
    var box = document.querySelector('.evt[data-type="' + t + '"] input');
    return box && box.checked;
  }});
}}

// Lanes are packed with no gaps, so toggling any type off moves every lane
// below it up one. Rebuild the y values for whatever is on and re-label the
// axis to match. y is derived from each trace's own point count: a line trace
// is [low, high, null] per event, a hover trace one point per event.
function _relayoutLanes() {{
  var on = _visibleTypes();
  var indices = [];
  var ys = [];
  var longest = 0;

  on.forEach(function(type, lane) {{
    if (type.length > longest) longest = type.length;
    var low = lane - LANE_HALF, high = lane + LANE_HALF;
    LANE_SPECS[type].forEach(function(spec) {{
      var y = [], i;
      if (spec[1] === 'line') {{
        for (i = 0; i < spec[2]; i++) {{ y.push(low, high, null); }}
      }} else {{
        for (i = 0; i < spec[2]; i++) {{ y.push(lane); }}
      }}
      indices.push(spec[0]);
      ys.push(y);
    }});
  }});

  var n = on.length;
  var layout = {{
    'yaxis.range': n ? [n - 0.5, -0.5] : [0, 1],
    'yaxis.tickvals': n ? on.map(function(_, i) {{ return i; }}) : [],
    'yaxis.ticktext': on,
    'yaxis.showticklabels': n > 0,
    'margin.l': n ? Math.min(220, Math.max(60, longest * 7 + 16)) : 12
  }};
  if (HEIGHT_AUTO) {{
    layout.height = LANE_CHROME + Math.max(MIN_LANE_AREA, n * LANE_HEIGHT);
  }}

  var gd = document.getElementById('{_DIV_ID}');
  if (indices.length) {{
    Plotly.update(gd, {{y: ys}}, layout, indices);
  }} else {{
    Plotly.relayout(gd, layout);
  }}
}}

function _updateCounts() {{
  var total = 0;
  document.querySelectorAll('#controls input[type=checkbox]').forEach(function(b) {{
    if (b.checked) total++;
  }});
  document.getElementById('rail-meta').textContent =
    NUM_TYPES + ' types in this game · ' + (total ? total + ' on chart' : 'none on chart');
  var clear = document.querySelector('.clear');
  clear.style.color = total ? HOME_COLOR : '#475569';
  clear.style.cursor = total ? 'pointer' : 'default';
  document.querySelectorAll('.group').forEach(function(g) {{
    var on = g.querySelectorAll('input:checked').length;
    var badge = g.querySelector('.badge');
    badge.textContent = on + ' on';
    badge.hidden = (on === 0);
  }});
}}

function _toggleGroup(head) {{
  var g = head.parentNode;
  var open = g.classList.toggle('open');
  g.querySelector('.group-body').hidden = !open;
}}

function _clearAll() {{
  var gd = document.getElementById('{_DIV_ID}');
  var indices = [];
  document.querySelectorAll('#controls input[type=checkbox]').forEach(function(b) {{
    if (b.checked) {{
      b.checked = false;
      indices = indices.concat(JSON.parse(b.dataset.indices));
    }}
  }});
  if (indices.length) {{
    Plotly.restyle(gd, {{visible: false}}, indices);
  }}
  _relayoutLanes();
  _updateCounts();
}}

function _filter(q) {{
  q = q.trim().toLowerCase();
  var groups = document.querySelectorAll('.group');
  // Remember how the groups were left before the first keystroke, so clearing
  // the box restores that rather than leaving everything expanded.
  if (q && _preSearchOpen === null) {{
    _preSearchOpen = [];
    groups.forEach(function(g) {{ _preSearchOpen.push(g.classList.contains('open')); }});
  }}
  var anyMatch = false;
  groups.forEach(function(g, i) {{
    var shown = 0;
    g.querySelectorAll('.evt').forEach(function(row) {{
      var hit = !q || row.dataset.type.indexOf(q) !== -1;
      row.hidden = !hit;
      if (hit) shown++;
    }});
    g.hidden = (shown === 0);
    if (shown) anyMatch = true;
    var body = g.querySelector('.group-body');
    if (q) {{
      g.classList.add('open');
      body.hidden = false;
    }} else {{
      var was = _preSearchOpen ? _preSearchOpen[i] : g.classList.contains('open');
      g.classList.toggle('open', was);
      body.hidden = !was;
    }}
  }});
  if (!q) _preSearchOpen = null;
  document.getElementById('no-match').hidden = anyMatch;
}}

function _fmtTime(s) {{
  var p = Math.floor(s / 1200);
  var m = Math.floor((s - p * 1200) / 60);
  var ss = (s - p * 1200) % 60;
  return 'P' + (p + 1) + ' ' + m + '.' + (ss < 10 ? '0' : '') + ss;
}}

function _teamBlock(name, color, rec) {{
  var rows = rec.players.map(function(pr) {{
    var w = Math.min(100, pr[1] / TOI_CEIL * 100);
    return '<div class="toi-row">' +
      '<span class="pos">' + (TOI_POS[pr[0]] || '') + '</span>' +
      '<span class="pname">' + TOI_NAMES[pr[0]] + '</span>' +
      '<span class="bar"><i style="width: ' + w.toFixed(1) +
        '%; background: ' + color + '"></i></span>' +
      '<span class="secs">' + pr[1] + 's</span>' +
    '</div>';
  }}).join('');
  return '<div class="toi-team">' +
    '<div class="toi-team-head">' +
      '<i class="dot" style="background: ' + color + '"></i>' +
      '<span class="toi-team-name">' + name + '</span>' +
      '<span class="spacer"></span>' +
      '<span class="toi-avg">avg <b>' + rec.avg + '</b> s</span>' +
    '</div>' +
    (rows || '<div class="toi-none">no skaters on ice</div>') +
  '</div>';
}}

function _setTime(s) {{
  if (s < 0) s = 0;
  if (s >= TOI_DATA.length) s = TOI_DATA.length - 1;
  var rec = TOI_DATA[s];
  var label = _fmtTime(s);

  document.getElementById('toi-box').innerHTML =
    '<div class="toi-grid">' +
      _teamBlock(HOME_NAME, HOME_COLOR, rec.h) +
      _teamBlock(AWAY_NAME, AWAY_COLOR, rec.a) +
    '</div>';

  var chip = document.getElementById('toi-time');
  chip.textContent = label;
  chip.hidden = false;

  var update = {{}};
  update['shapes[' + PLAYHEAD_SHAPE + '].x0'] = s;
  update['shapes[' + PLAYHEAD_SHAPE + '].x1'] = s;
  update['shapes[' + PLAYHEAD_SHAPE + '].visible'] = true;
  update['annotations[' + PLAYHEAD_NOTE + '].x'] = s;
  update['annotations[' + PLAYHEAD_NOTE + '].text'] = label;
  update['annotations[' + PLAYHEAD_NOTE + '].visible'] = true;
  Plotly.relayout(document.getElementById('{_DIV_ID}'), update);
}}

(function() {{
  _updateCounts();
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
    _setTime(Math.round(x));
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
