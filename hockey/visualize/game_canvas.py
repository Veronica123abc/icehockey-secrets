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

# Bump to invalidate cached canvas HTML after visualization changes
# (mirrors PLOT_VERSION in shift_toi.py).
#
# 5: the metric rail is built from hockey/derive/metric_catalog.py instead of
#    a table kept in this file, so every lane label changed. A warm worker
#    would otherwise keep serving the old rail from _plotly_cache.
# 6: "Controlled entries" and "Dump-ins" merged into one "Entries" section.
#    Lane keys are unchanged -- only the rail's grouping moved -- but the
#    cached HTML still holds the old headings.
# 7: context filter (period / manpower / goalies). Segments carry a per-event
#    context code the older cached HTML has no array for, so serving it would
#    break the new JS.
CANVAS_VERSION = 7


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

# The rail's grouping is no longer declared here. It is the metric layer's own
# shape -- module -> population -> filter group -> item -- read from
# hockey/derive/metric_catalog.py by _group_event_types and _module_blocks
# below, so there is no display-only table to drift out of step with the
# metrics themselves.

# Ticking a metric this common draws a wall of lines rather than a signal; the
# count is flagged so you can see that before you tick it.
_DENSE_THRESHOLD = 300

# Which team an event is attributed to. Traces are split by side so the team
# selector is a visibility toggle rather than a re-plot.
_SIDE_HOME = "h"
_SIDE_AWAY = "a"
_SIDE_NONE = "n"
_SIDES = (_SIDE_HOME, _SIDE_AWAY, _SIDE_NONE)
# Team-selector value meaning "don't filter".
_TEAM_BOTH = "both"

# Lane geometry. A lane is one y unit; ticks fill the middle 70% of it.
_LANE_HALF = 0.35
# Vertical space the chart needs besides the lanes themselves (the x axis and
# the top/bottom margins), used when sizing the chart to its lane count.
_LANE_CHROME = 54
# Floor for the lane area. One lane's worth of plot is a sliver that's awkward
# to click for a TOI readout, so short selections still get a usable strip.
_MIN_LANE_AREA = 96


# The lane tree comes from the metric layer, not from a table kept here.
# hockey/derive/metric_catalog.py assembles it from the eight derive modules:
# module -> population -> filter group -> item, where each item is the same
# Event -> bool predicate the metrics themselves are computed with. So the
# selector and the metrics can no longer disagree -- adding a filter item to a
# module puts it on the canvas, and there is no second copy to update.
#
# Importing it must stay filesystem-free: the canvas has to render in
# ``db_only`` deployments, where DATA_ROOT_DIR is unset. The metric modules
# resolve their settings lazily for exactly this reason.
from hockey.derive import metric_catalog as catalog
from hockey.derive import context_filter as ctx

# --- Context codes --------------------------------------------------------
# Which SITUATION an event happened in -- period, manpower, goalies -- comes
# from hockey/derive/context_filter.py, which is deliberately ignorant of this
# file so the same classification can back any other visual.
#
# Each event is reduced to one small integer so the browser can narrow the
# chart the way it already narrows by team and player, with no round trip:
#
#     code = period*100 + manpower*10 + goalies
#
# with 9 in any position meaning "the event does not say". One int per event
# rather than three arrays -- a segment already carries a time and a player id
# for each of ~16k lane memberships, and this keeps the page from growing a
# third again.
#
# The TEAM dimension is deliberately absent: the canvas already has a team
# selector, and a second one would be two controls fighting over one filter.
_CTX_PERIODS = ctx.PERIODS[1:]          # "All" is a selection, not a value
_CTX_MANPOWER = ctx.MANPOWERS
_CTX_GOALIES = ctx.GOALIE_SITUATIONS
_CTX_UNKNOWN = 9


def _context_index(value, table) -> int:
    return table.index(value) if value in table else _CTX_UNKNOWN


def _context_code(event: Event) -> int:
    """Pack an event's period, manpower and goalie situation into one int."""
    return (_context_index(ctx.period_of(event), _CTX_PERIODS) * 100
            + _context_index(ctx.manpower_of(event), _CTX_MANPOWER) * 10
            + _context_index(ctx.goalies_of(event), _CTX_GOALIES))

# Lanes that carry another lane's events with the sides swapped.
#
# Empty now. The old hand-written table synthesised "against" lanes (scoring
# chance against, carry to slot against, ...) by mirroring an event onto the
# other bench, because the metric list had no real opponent events. The
# catalog does: defensive_events supplies controlledentryagainst, blocks and
# checks as genuine events with their own filters, so a mirrored copy would be
# a second, weaker version of a lane that already exists. _build_figure still
# consults this, so restoring mirrors means filling this set -- nothing else.
_MIRRORED_LANES: frozenset = frozenset()

_FLIP_SIDE = {_SIDE_HOME: _SIDE_AWAY, _SIDE_AWAY: _SIDE_HOME, _SIDE_NONE: _SIDE_NONE}


def _display_lanes(event: Event) -> tuple[str, ...]:
    """Every lane this event belongs to; empty if no module covers it.

    An event lands in its population's "All" lane plus one lane per matching
    filter item, so a pass is typically in five or six lanes at once -- the
    groups are independent axes, not alternatives.

    Roughly a third of a game's events (goals, assists, faceoffs, penalties,
    loose-puck recoveries, plain carries) belong to no population and so get
    no lane. That is the scope of the eight modules, not a gap here.
    """
    return catalog.lanes_for_event(event)


def _team_label(team) -> str:
    """Display label for a team, without the doubling display_name can carry.

    TeamInfo.display_name is "<location> <name>", which supplier playsequence
    strings match exactly -- TeamResolver.team_id_from_string depends on that
    and raises on a mismatch, so it must not change. But it reads as
    "Brynas Brynas IF" whenever the name already carries the location, so the
    UI uses this instead.
    """
    location = (team.location or "").strip()
    name = (team.name or "").strip()
    if not location:
        return name
    if not name:
        return location
    return name if name.startswith(location) else f"{location} {name}"


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
            {lane for e in game.events if e.name and e.t is not None
             for lane in _display_lanes(e)}
        )
        self._preselected: set[str] = set()
        # Rail reading order, which is also the order lanes are packed in.
        self._display_order: list[str] = [
            name for _, names in self._group_event_types() for name in names
        ]
        # How many events of each type -- shown in the rail so the cost of
        # ticking a type is visible before you tick it.
        self._event_counts: Counter[str] = Counter(
            lane for e in game.events if e.name and e.t is not None
            for lane in _display_lanes(e)
        )
        # Events per player, shown beside each roster row so it's obvious who
        # actually played (a scratch reads 0).
        self._player_counts: Counter[int] = Counter(
            e.player_id for e in game.events
            if e.player_id is not None and e.name and e.t is not None
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
        known = set(self._event_types)
        self._preselected.update(
            lane for e in events for lane in _display_lanes(e) if lane in known
        )

    def to_html(self, back_href: str | None = None) -> str:
        """The canvas as a standalone HTML page.

        ``back_href`` adds a link back to wherever the page was reached from;
        leave it None for a standalone file, which has nowhere to go back to.
        """
        return self._render_html(back_href=back_href)

    def show(self) -> None:
        """Render the visual on screen (opens in the browser)."""
        html = self.to_html()
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

    def _event_side(self, event: Event) -> str:
        """Which side an event belongs to: ``h``, ``a`` or ``n`` (no team).

        Attributed to the acting team. team_id is populated on every event;
        team_id_in_possession is null on ~40% of them (all scoring chances,
        entries and faceoffs), which would leave most events unattributed.
        """
        team = event.team_id if event.team_id is not None else event.team_id_in_possession
        if team == self._game.info.home_team.id:
            return _SIDE_HOME
        if team == self._game.info.away_team.id:
            return _SIDE_AWAY
        return _SIDE_NONE

    def _side_color(self, side: str) -> str:
        if side == _SIDE_HOME:
            return self._props["home-team-graph-color"]
        if side == _SIDE_AWAY:
            return self._props["away-team-graph-color"]
        return _NEUTRAL_EVENT_COLOR

    def _side_name(self, side: str) -> str:
        if side == _SIDE_HOME:
            return _team_label(self._game.info.home_team)
        if side == _SIDE_AWAY:
            return _team_label(self._game.info.away_team)
        return ""

    def _event_color(self, event: Event) -> str:
        return self._side_color(self._event_side(event))

    def _build_figure(self) -> go.Figure:
        """
        Build the timeline figure.

        Also populates ``self._segments``: event type -> one entry per side,
        each carrying the two trace indices that render it (``l``ine and
        ``h``over), the ``s``ide, and the event ``t``imes, ``p``layer ids and
        ``c``ontext codes behind them. The browser re-derives the traces from
        that whenever a filter changes.
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
        known = set(self._event_types)
        for e in self._game.events:
            if e.t is None or not e.name:
                continue
            for lane in _display_lanes(e):
                if lane in known:
                    events_by_type[lane].append(e)

        # Lanes: each visible type occupies one row of the y axis, so types
        # stay separable instead of overprinting each other. Lanes are packed
        # (no gaps) in display order, which means toggling a type off reflows
        # the ones below it -- the browser redoes this in _redraw().
        lanes = self._initial_lanes()
        lane_of = {etype: i for i, etype in enumerate(lanes)}

        # Traces are split by side (home / away / unattributed) so the team
        # selector only has to flip `visible` -- no re-plotting. Each side gets
        # its own line trace and its own hover trace, so hover targets vanish
        # with the ticks they belong to.
        segments: dict[str, list[dict]] = {}
        for etype in self._display_order:
            lane = lane_of.get(etype, 0)
            low, high = lane - _LANE_HALF, lane + _LANE_HALF
            visible = etype in self._preselected   # team filter starts at "both"
            specs: list[dict] = []

            # An "against" lane is the same events seen from the other
            # bench, so it draws on the opposite side and credits nobody: the
            # player who made the play is on the team the metric is against.
            mirrored = etype in _MIRRORED_LANES
            by_side: dict[str, list[Event]] = defaultdict(list)
            for e in events_by_type[etype]:
                side = self._event_side(e)
                by_side[_FLIP_SIDE[side] if mirrored else side].append(e)

            for side in _SIDES:
                group = by_side.get(side)
                if not group:
                    continue
                color = self._side_color(side)

                xs: list = []
                ys: list = []
                for e in group:
                    xs += [e.t, e.t, None]
                    ys += [low, high, None]
                line_idx = len(fig.data)
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines",
                    line=dict(color=color, width=1),
                    name=etype,
                    hoverinfo="skip",
                    visible=visible,
                    showlegend=False,
                ))

                # Invisible on-lane markers give a large hover target so the
                # event's details show on hover (thin lines are hard to hit).
                # Hover text is filled in by the browser (_redraw), so there is
                # only one implementation of the format.
                hover_idx = len(fig.data)
                fig.add_trace(go.Scatter(
                    x=[e.t for e in group],
                    y=[lane] * len(group),
                    mode="markers",
                    marker=dict(size=16, opacity=0),
                    name=etype,
                    hovertemplate="%{hovertext}<extra></extra>",
                    visible=visible,
                    showlegend=False,
                ))

                # The event times, player ids and context codes behind these
                # two traces. The browser re-derives x/y from them whenever a
                # filter changes -- neither a player nor a context filter can
                # be expressed as trace visibility, since one trace mixes
                # every player and every situation on that side.
                specs.append({
                    "l": line_idx,
                    "h": hover_idx,
                    "s": side,
                    "t": [round(e.t, 1) for e in group],
                    "p": ([None] * len(group) if mirrored
                          else [e.player_id for e in group]),
                    "c": [_context_code(e) for e in group],
                })

            segments[etype] = specs

        self._segments = segments

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
            # No explicit height/width: that would set autosize=false and make
            # Plotly.Plots.resize a no-op. The .plot-wrap div owns the size,
            # and the figure measures itself against it.
            hovermode="closest",
            margin=dict(t=26, b=28, l=_lane_margin(lanes), r=12),
        )
        return fig

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

    def _scoreboard_html(self, back_href: str | None = None) -> str:
        """The identity band: teams, score and game metadata."""
        props = self._props
        info = self._game.info
        back = ""
        if back_href:
            back = (f'<a class="back" id="back-link" href="{escape(back_href)}">'
                    f'&larr;</a>')

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
  {back}
  <span class="team"><i class="dot" style="background: {props['home-team-graph-color']}"></i>{_team_label(info.home_team)}</span>
  {score}
  <span class="team"><i class="dot" style="background: {props['away-team-graph-color']}"></i>{_team_label(info.away_team)}</span>
  <span class="sep"></span>
  <span class="meta">{' · '.join(meta)}</span>
  <span class="spacer"></span>
  <span class="counts">{len(self._game.events):,} events · {len(self._event_types)} types</span>
  <span class="sep"></span>
  <span class="report-hint" id="report-hint"></span>
  <button type="button" class="btn primary" id="report-btn" onclick="_openReport()">Generate report</button>
</div>"""

    def _team_selector_html(self) -> str:
        """Segmented control filtering the chart to one team's events.

        Doubles as the colour key, so there is no separate legend. The
        unattributed swatch only appears if the game actually has events with
        no team on them.
        """
        info = self._game.info
        segments = [
            (_TEAM_BOTH, "Both teams", None),
            (_SIDE_HOME, _team_label(info.home_team), self._side_color(_SIDE_HOME)),
            (_SIDE_AWAY, _team_label(info.away_team), self._side_color(_SIDE_AWAY)),
        ]
        buttons = []
        for value, label, color in segments:
            active = " active" if value == _TEAM_BOTH else ""
            swatch = (f'<i class="dot" style="background: {color}"></i>'
                      if color else "")
            buttons.append(
                f'<button type="button" class="seg{active}" data-side="{value}"'
                f' onclick="_setTeam(\'{value}\')">{swatch}{label}</button>'
            )

        unattributed = ""
        if any(self._event_side(e) == _SIDE_NONE
               for e in self._game.events if e.t is not None):
            unattributed = (
                f'<span class="legend-note">'
                f'<i class="dot" style="background: {_NEUTRAL_EVENT_COLOR}"></i>'
                f'unattributed</span>'
            )
        return f'<div class="segbar" id="team-sel">{"".join(buttons)}</div>{unattributed}'

    def _context_bar_html(self) -> str:
        """The context bar: period, manpower and goalie situation.

        The values and their order come from hockey/derive/context_filter.py,
        so this renders whatever that module defines rather than restating it.

        TEAM is not here on purpose. The context filter has a team dimension,
        but this page already has a team selector beside the chart, and two
        controls driving one filter is a bug waiting to happen. The team
        segmented control IS the team dimension.

        Each button carries the integer index the packed context code uses, so
        the browser compares numbers rather than re-deriving labels. Period's
        "All" is index -1: not a value an event can have, but a selection that
        drops the constraint.
        """
        groups = [
            (ctx.PERIOD, [(ctx.ALL, -1, ctx.ALL)]
             + [(value, i, value) for i, value in enumerate(_CTX_PERIODS)],
             {ctx.ALL}),
            (ctx.MANPOWER,
             [(value, i, value) for i, value in enumerate(_CTX_MANPOWER)],
             {ctx.ES}),
            (ctx.GOALIES,
             [(short, i, full) for i, (full, short) in enumerate(
                 zip(_CTX_GOALIES, ("Both", "Goalie out", "Opp. goalie out")))],
             {"Both"}),
        ]
        blocks = []
        for dimension, buttons, active in groups:
            rendered = []
            for label, index, title in buttons:
                on = " active" if label in active else ""
                rendered.append(
                    f'<button type="button" class="ctx{on}" data-dim="{dimension}"'
                    f' data-idx="{index}" title="{escape(title)}"'
                    f' onclick="_setCtx(this)">{escape(label)}</button>'
                )
            blocks.append(
                f'    <div class="ctxgrp" data-dim="{dimension}">'
                f'<span class="ctxlabel">{escape(dimension)}</span>'
                f'{"".join(rendered)}</div>'
            )
        return ('  <div class="ctxbar" id="ctx-bar">\n'
                + "\n".join(blocks)
                + '\n    <span class="spacer"></span>'
                + '\n    <span class="ctxmeta" id="ctx-meta"></span>\n  </div>')

    def _group_event_types(self) -> list[tuple[str, list[str]]]:
        """This game's lanes bucketed by population, in catalog order.

        One bucket per population that actually occurs in this game, holding
        its lanes in the order the metric module declares them ("All" first,
        then each filter group's items). A lane with no events in this game is
        dropped, which is what stops the rail listing filter items the
        supplier never produced -- an untagged rush differential, say, or a
        pass type this league does not use.

        There is no "Other" bucket any more: a lane exists only because a
        module defines it, so nothing can fall outside the tree.
        """
        present = set(self._event_types)
        groups: list[tuple[str, list[str]]] = []
        for module in catalog.TREE:
            for population in module.populations:
                lanes = [lane.key for lane in population.lanes
                         if lane.key in present]
                if lanes:
                    groups.append((population.label, lanes))
        return groups

    def _module_blocks(self) -> list[tuple[str, list[tuple[str, list[str]]]]]:
        """The rail tree: module -> its populations present in this game.

        The module level is display only -- lanes are keyed by population and
        item, so this adds a heading without touching the lane identity the
        chart, the report and the CSV all share.
        """
        by_population = dict(self._group_event_types())
        blocks: list[tuple[str, list[tuple[str, list[str]]]]] = []
        for module in catalog.TREE:
            populations = [
                (population.label, by_population[population.label])
                for population in module.populations
                if population.label in by_population
            ]
            if populations:
                blocks.append((module.label, populations))
        return blocks

    def _population_subgroups(self, population_label: str,
                              lanes: list[str]) -> list[tuple[str, list[str]]]:
        """One population's lanes split by the filter group they came from.

        ``All`` has no group of its own and leads the list under an empty
        heading, so it reads as the population total rather than as a member
        of whichever group happens to come first.
        """
        present = set(lanes)
        out: list[tuple[str, list[str]]] = []
        for module in catalog.TREE:
            for population in module.populations:
                if population.label != population_label:
                    continue
                if population.all_lane.key in present:
                    out.append(("", [population.all_lane.key]))
                for group, group_lanes in population.groups:
                    keys = [lane.key for lane in group_lanes if lane.key in present]
                    if keys:
                        out.append((group, keys))
        return out

    def _roster_by_side(self) -> list[tuple[str, list]]:
        """The two rosters, home first, each sorted by jersey number."""
        team_ids = {
            _SIDE_HOME: self._game.info.home_team.id,
            _SIDE_AWAY: self._game.info.away_team.id,
        }
        out = []
        for side in (_SIDE_HOME, _SIDE_AWAY):
            players = [
                p for p in self._game.roster.players.values()
                if p.team_id == team_ids[side]
            ]
            players.sort(key=lambda p: (p.jersey_number is None,
                                        p.jersey_number or 0))
            out.append((side, players))
        return out

    def _on_ice_for_js(self) -> dict[int, list[list[float]]]:
        """player id -> the merged [start, end) spans they were on the ice.

        Backs the "player WOI" mode: an event counts when its time falls inside
        one of these spans, whoever the event itself is attributed to. Spans
        rather than per-event on-ice sets -- 742 intervals against 5,583
        events, and the browser only has to test a time.
        """
        by_player: dict[int, list[list[float]]] = defaultdict(list)
        for x in self._game.toi:
            end = self._end_time if x.end_t is None else x.end_t
            if end <= x.start_t:
                continue
            by_player[x.player_id].append([round(x.start_t, 1), round(end, 1)])

        merged_by_player: dict[int, list[list[float]]] = {}
        for pid, spans in by_player.items():
            spans.sort()
            merged = [spans[0]]
            for start, end in spans[1:]:
                if start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            merged_by_player[pid] = merged
        return merged_by_player

    def _player_mode_html(self) -> str:
        """Switch between "attributed to the player" and "player on the ice"."""
        return (
            '<div class="segbar modesel" id="mode-sel">'
            '<button type="button" class="seg active" data-mode="player"'
            ' onclick="_setPlayerMode(\'player\')">Player</button>'
            '<button type="button" class="seg" data-mode="woi"'
            ' onclick="_setPlayerMode(\'woi\')">Player WOI</button>'
            '</div>'
        )

    def _player_names_for_js(self) -> dict[int, str]:
        """player id -> display name, for hover text built in the browser."""
        return {
            p.player_id: escape(self._player_name(p.player_id))
            for p in self._game.roster.players.values()
        }

    def _player_meta_for_js(self) -> dict[int, dict]:
        """player id -> the roster facts the report tabulates by.

        Only players the roster pane lists, so the report and the pane agree
        on who exists; ``s`` is the side, which the team filter narrows on.
        """
        meta: dict[int, dict] = {}
        for side, players in self._roster_by_side():
            for p in players:
                meta[p.player_id] = {
                    "n": "" if p.jersey_number is None else p.jersey_number,
                    # Escaped here: the report writes these with innerHTML.
                    "name": escape(self._player_name(p.player_id)),
                    "pos": escape(p.position or ""),
                    "s": side,
                }
        return meta

    def _report_info(self) -> dict:
        """Title, subtitle and download filename for the report sheet."""
        info = self._game.info
        meta = []
        if info.date:
            meta.append(self._format_date(info.date))
        if info.stage:
            meta.append(_STAGE_LABELS.get(info.stage, info.stage.capitalize()))
        meta.append(f"Game {info.game_id}")
        if info.home_final_score is not None and info.away_final_score is not None:
            meta.append(f"{info.home_final_score}–{info.away_final_score}")
        return {
            "title": escape(f"{_team_label(info.home_team)} vs "
                            f"{_team_label(info.away_team)} — player report"),
            "meta": escape(" · ".join(meta)),
            "slug": f"game-{info.game_id}-player-report",
        }

    def _report_html(self) -> str:
        """The report overlay: a shell the browser fills in on demand.

        A direct child of <body> so the print stylesheet can hide everything
        else and send just the sheet to the PDF.
        """
        return """<div class="report-overlay" id="report-overlay" hidden onclick="_backdrop(event)">
  <div class="report-modal" role="dialog" aria-modal="true" aria-labelledby="report-title">
    <div class="report-bar">
      <span class="section-heading" id="report-title">Player report</span>
      <span class="report-sub" id="report-sub"></span>
      <span class="spacer"></span>
      <span class="report-hint">PDF opens your browser\'s print dialog — pick "Save as PDF"</span>
      <button type="button" class="btn" onclick="_downloadCsv()">Download CSV</button>
      <button type="button" class="btn primary" onclick="_downloadPdf()">Download PDF</button>
      <button type="button" class="btn ghost" onclick="_closeReport()">Close</button>
    </div>
    <div class="report-scroll"><div class="report-sheet" id="report-body"></div></div>
  </div>
</div>"""

    def _roster_html(self) -> str:
        """The roster pane: per-team player checkboxes filtering the chart.

        Selecting nothing means "every player" -- the filter only narrows once
        at least one player is picked.
        """
        blocks = []
        for side, players in self._roster_by_side():
            rows = []
            for p in players:
                count = self._player_counts.get(p.player_id, 0)
                number = "" if p.jersey_number is None else p.jersey_number
                rows.append(
                    f'      <label class="plr" data-pid="{p.player_id}">'
                    f'<input type="checkbox" onchange="_togglePlayer(this)">'
                    f'<span class="plr-num">{number}</span>'
                    f'<span class="plr-name">{escape(self._player_name(p.player_id))}</span>'
                    f'<span class="plr-pos">{escape(p.position or "")}</span>'
                    f'<span class="plr-count">{count:,}</span></label>'
                )
            blocks.append(f"""    <div class="team-block" data-side="{side}">
      <div class="roster-team">
        <i class="dot" style="background: {self._side_color(side)}"></i>
        <span class="roster-team-name">{self._side_name(side)}</span>
        <span class="spacer"></span>
        <span class="roster-size">{len(players)}</span>
      </div>
{chr(10).join(rows)}
    </div>""")
        return "\n".join(blocks)

    def _rail_html(self) -> str:
        """The metric rail: module -> population -> filter group -> item.

        The tree is the metric layer's own structure, read from
        hockey/derive/metric_catalog.py, rather than a display-only copy of it
        kept in this file.

        A row SHOWS just the item ("On Net") because the group heading above
        it already says which population it belongs to; its ``data-type`` is
        the full lane key ("Shots · On Net"), which is what the chart, the
        report, the CSV and the search box all key on. Filter-group headings
        inside a population are plain captions, not another collapsible level
        -- four levels of disclosure in a 300px rail is more clicking than
        reading.

        Modules and populations start collapsed unless they hold a
        pre-selected lane, so an untouched canvas opens as a short menu rather
        than a 145-row list.
        """
        chevron = (
            '<svg class="chev" width="14" height="14" viewBox="0 0 16 16" '
            'fill="none"><path d="M6 4 L10 8 L6 12" stroke="'
            f'{self._props["axis-color"]}'
            '" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round"/></svg>'
        )
        blocks = []
        for module_label, populations in self._module_blocks():
            module_lanes = [key for _, lanes in populations for key in lanes]
            module_on = sum(1 for key in module_lanes if key in self._preselected)

            groups = []
            for population_label, lanes in populations:
                on = sum(1 for key in lanes if key in self._preselected)
                rows = []
                for heading, keys in self._population_subgroups(population_label, lanes):
                    if heading:
                        rows.append(
                            f'            <div class="sub">{escape(heading)}</div>')
                    for key in keys:
                        count = self._event_counts[key]
                        checked = " checked" if key in self._preselected else ""
                        dense = " dense" if count >= _DENSE_THRESHOLD else ""
                        item = catalog.BY_KEY[key].item
                        rows.append(
                            f'            <label class="evt" data-type="{escape(key)}">'
                            f'<input type="checkbox" onchange="_toggle(this)"{checked}>'
                            f'<span class="evt-name">{escape(item)}</span>'
                            f'<span class="evt-count{dense}">{count:,}</span></label>'
                        )
                badge = (f'<span class="badge">{on} on</span>' if on
                         else '<span class="badge" hidden></span>')
                body_hidden = "" if on else " hidden"
                groups.append(f"""        <div class="group{' open' if on else ''}">
          <div class="group-head" onclick="_toggleGroup(this)">
            {chevron}
            <span class="group-name">{escape(population_label)}</span>
            <span class="group-size">{len(lanes)}</span>
            <span class="spacer"></span>{badge}
          </div>
          <div class="group-body"{body_hidden}>
{chr(10).join(rows)}
          </div>
        </div>""")

            module_badge = (f'<span class="badge">{module_on} on</span>' if module_on
                            else '<span class="badge" hidden></span>')
            module_hidden = "" if module_on else " hidden"
            blocks.append(f"""      <div class="module{' open' if module_on else ''}">
        <div class="module-head" onclick="_toggleModule(this)">
          {chevron}
          <span class="module-name">{escape(module_label)}</span>
          <span class="group-size">{len(module_lanes)}</span>
          <span class="spacer"></span>{module_badge}
        </div>
        <div class="module-body"{module_hidden}>
{chr(10).join(groups)}
        </div>
      </div>""")
        return "\n".join(blocks)

    def _render_html(self, back_href: str | None = None) -> str:
        """Wrap the figure in an HTML page with per-event-type checkboxes."""
        fig = self._build_figure()
        props = self._props

        fig_html = fig.to_html(
            full_html=False, include_plotlyjs="cdn", div_id=_DIV_ID,
            config={"responsive": True},
        )
        # The plot is sized by this wrapper, not by the figure: a div with an
        # explicit height reserves the space in the flow, so the chart can't
        # draw over the card below it when the lane count changes.
        plot_height = self._chart_height(len(self._initial_lanes()))

        toi_data, toi_names, toi_positions = self._toi_embed()
        toi_ceiling = self._toi_bar_ceiling()

        rail_html = self._rail_html()

        num_types = len(self._event_types)
        selected = len(self._preselected)
        rail_meta = (f"{num_types} metrics in this game · "
                     + (f"{selected} on chart" if selected else "none on chart"))

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{props['title']} — {_team_label(self._game.info.home_team)} vs {_team_label(self._game.info.away_team)}</title>
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
  .back {{
    font-size: 18px;
    line-height: 1;
    color: {props['font-color']};
    text-decoration: none;
    padding: 4px 8px;
    margin-left: -8px;
    border-radius: 5px;
  }}
  .back:hover {{ color: {props['title-color']}; background: rgba(148, 163, 184, 0.1); }}
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
    flex-wrap: wrap;
    gap: 20px;
    padding: 20px 24px 24px;
  }}
  .card {{
    background: {props['card-color']};
    border: 1px solid {props['border-color']};
    border-radius: 8px;
  }}
  .rail {{
    width: 300px;
    flex-shrink: 0;
    padding: 16px;
    max-height: calc(100vh - 132px);
    overflow-y: auto;
  }}
  .roster {{
    width: 264px;
    flex-shrink: 0;
    padding: 16px;
    max-height: calc(100vh - 132px);
    overflow-y: auto;
  }}
  .team-block {{ margin-top: 12px; }}
  .team-block.dimmed {{ opacity: 0.35; }}
  .roster-team {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 8px;
    margin-bottom: 4px;
    border-bottom: 1px solid {props['border-color']};
  }}
  .roster-team .dot {{ width: 9px; height: 9px; }}
  .roster-team-name {{ font-size: 12.5px; font-weight: 600; color: {props['title-color']}; }}
  .roster-size {{ font-size: 11px; color: {props['axis-color']}; }}
  .plr {{
    display: flex;
    align-items: center;
    gap: 8px;
    height: 27px;
    padding: 0 8px;
    margin: 0 -8px;
    border-radius: 5px;
    font-size: 12.5px;
    color: {props['font-color']};
    cursor: pointer;
    user-select: none;
  }}
  .plr:hover {{
    background: rgba(148, 163, 184, 0.08);
    color: {props['text-color']};
  }}
  .plr:has(input:checked) {{ background: rgba(96, 165, 250, 0.09); }}
  .plr:has(input:checked) .plr-name {{ color: {props['text-color']}; }}
  .plr input {{
    width: 14px;
    height: 14px;
    margin: 0;
    flex-shrink: 0;
    accent-color: {props['home-team-graph-color']};
    cursor: pointer;
  }}
  .plr-num {{
    width: 18px;
    flex-shrink: 0;
    text-align: right;
    font-size: 11px;
    color: {props['axis-color']};
    font-variant-numeric: tabular-nums;
  }}
  .plr-name {{
    flex-grow: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .plr-pos {{
    flex-shrink: 0;
    font-size: 10px;
    font-weight: 600;
    color: {props['axis-color']};
  }}
  .plr-count {{
    width: 30px;
    flex-shrink: 0;
    text-align: right;
    font-size: 11px;
    color: {props['axis-color']};
    font-variant-numeric: tabular-nums;
  }}
  /* Floor the chart column so a narrow window wraps the panes onto the next
     row instead of crushing the timeline. */
  .main {{ flex-grow: 1; flex-basis: 460px; min-width: 460px; }}
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
  /* Three levels: module > population (.group) > filter-group caption (.sub).
     Only the first two collapse; a caption is a label, not a control. */
  .module {{ border-top: 1px solid {props['border-color']}; }}
  .module:first-child {{ border-top: 0; }}
  .module-head {{
    display: flex;
    align-items: center;
    gap: 7px;
    height: 36px;
    cursor: pointer;
    user-select: none;
  }}
  .module-name {{
    font-size: 12.5px;
    font-weight: 700;
    color: {props['title-color']};
  }}
  .module-body {{ padding-left: 10px; }}
  .group-head {{
    display: flex;
    align-items: center;
    gap: 7px;
    height: 30px;
    cursor: pointer;
    user-select: none;
  }}
  .group-name {{ font-size: 12.5px; font-weight: 600; color: #cbd5e1; }}
  .group-size {{ font-size: 11px; color: {props['axis-color']}; }}
  .chev {{ flex-shrink: 0; transition: transform 120ms ease; }}
  /* Scoped with > so opening a module does not rotate the chevrons of the
     populations nested inside it. */
  .group.open > .group-head .chev {{ transform: rotate(90deg); }}
  .module.open > .module-head .chev {{ transform: rotate(90deg); }}
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
    padding: 0 0 8px 10px;
  }}
  .sub {{
    margin: 7px 0 1px;
    font-size: 10.5px;
    font-weight: 600;
    color: {props['axis-color']};
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .sub:first-child {{ margin-top: 2px; }}
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
  .ctxbar {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 18px;
    padding: 9px 0 11px;
    margin-bottom: 4px;
    border-bottom: 1px solid {props['border-color']};
  }}
  .ctxgrp {{ display: flex; align-items: center; gap: 4px; }}
  .ctxlabel {{
    margin-right: 4px;
    font-size: 10.5px;
    font-weight: 600;
    color: {props['axis-color']};
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .ctx {{
    padding: 3px 9px;
    border: 1px solid {props['border-color']};
    border-radius: 5px;
    background: {props['background-color']};
    font-family: inherit;
    font-size: 11.5px;
    color: {props['font-color']};
    cursor: pointer;
  }}
  .ctx:hover {{ color: {props['text-color']}; border-color: #475569; }}
  .ctx.active {{
    background: rgba(96, 165, 250, 0.16);
    border-color: rgba(96, 165, 250, 0.5);
    color: #cfe0fd;
    font-weight: 600;
  }}
  .ctxmeta {{
    font-size: 11px;
    color: {props['axis-color']};
    font-variant-numeric: tabular-nums;
  }}
  .timeline-card {{ padding: 18px 20px 14px; }}
  .plot-wrap {{ position: relative; width: 100%; }}
  /* to_html wraps the graph div in a plain <div>; that one needs a definite
     height too, or the graph div's height:100% resolves against auto and
     Plotly falls back to its 450px default and overflows the card. */
  .plot-wrap > div {{ height: 100%; }}
  .plot-wrap .plotly-graph-div {{ width: 100% !important; height: 100% !important; }}
  .card-head {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 4px;
  }}
  .head-right {{ display: flex; align-items: center; gap: 14px; margin-left: auto; }}
  .segbar {{
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 2px;
    background: {props['background-color']};
    border: 1px solid {props['border-color']};
    border-radius: 7px;
  }}
  .seg {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border: 0;
    border-radius: 5px;
    background: none;
    font-family: inherit;
    font-size: 12px;
    color: {props['font-color']};
    cursor: pointer;
  }}
  .seg:hover {{ color: {props['text-color']}; }}
  .seg.active {{
    background: {props['border-color']};
    color: {props['title-color']};
    font-weight: 600;
  }}
  .seg .dot {{ width: 8px; height: 8px; }}
  .modesel {{ margin: 11px 0 8px; }}
  .modesel .seg {{ flex-grow: 1; justify-content: center; }}
  .legend-note {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: {props['font-color']};
  }}
  .legend-note .dot {{ width: 8px; height: 8px; }}
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
  .btn {{
    font-family: inherit;
    font-size: 12px;
    padding: 6px 12px;
    border: 1px solid {props['border-color']};
    border-radius: 6px;
    background: {props['background-color']};
    color: {props['text-color']};
    cursor: pointer;
    white-space: nowrap;
  }}
  .btn:hover {{ border-color: #475569; color: {props['title-color']}; }}
  .btn.primary {{
    background: {props['home-team-graph-color']};
    border-color: {props['home-team-graph-color']};
    color: #0b1220;
    font-weight: 600;
  }}
  .btn.primary:hover {{ filter: brightness(1.08); color: #0b1220; }}
  .btn.ghost {{ background: none; border-color: transparent; color: {props['font-color']}; }}
  .report-hint {{ font-size: 11.5px; color: {props['axis-color']}; }}
  .report-overlay {{
    position: fixed;
    inset: 0;
    z-index: 40;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 26px;
    background: rgba(2, 6, 23, 0.74);
  }}
  .report-modal {{
    display: flex;
    flex-direction: column;
    width: min(1200px, 100%);
    max-height: 100%;
    background: {props['card-color']};
    border: 1px solid {props['border-color']};
    border-radius: 10px;
    overflow: hidden;
  }}
  .report-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
    padding: 13px 18px;
    border-bottom: 1px solid {props['border-color']};
  }}
  .report-sub {{
    font-size: 12px;
    color: {props['font-color']};
    font-variant-numeric: tabular-nums;
  }}
  .report-scroll {{ overflow: auto; padding: 22px; background: {props['background-color']}; }}
  /* The sheet is deliberately light: it is what the PDF will look like, so
     what is on screen is a preview of the printed page rather than a
     differently themed version of it. */
  .report-sheet {{
    width: fit-content;
    min-width: min(1100px, 100%);
    margin: 0 auto;
    padding: 30px 34px 34px;
    background: #ffffff;
    color: #0f172a;
    border-radius: 6px;
    font-size: 12px;
  }}
  .rep-title {{ font-size: 18px; font-weight: 700; margin-bottom: 5px; }}
  .rep-meta {{ font-size: 11.5px; color: #475569; }}
  .rep-filters {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 13px; }}
  .rep-chip {{
    font-size: 11px;
    color: #334155;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 9999px;
    padding: 2px 9px;
  }}
  .rep-team-head {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 24px 0 9px;
    font-size: 13px;
    font-weight: 700;
  }}
  .rep-table {{
    min-width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;
  }}
  .rep-table th, .rep-table td {{
    padding: 5px 7px;
    text-align: right;
    white-space: nowrap;
    border-bottom: 1px solid #e2e8f0;
  }}
  .rep-table th {{
    font-size: 10.5px;
    font-weight: 600;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid #94a3b8;
  }}
  .rep-table th.l, .rep-table td.l {{ text-align: left; }}
  .rep-table td.zero {{ color: #cbd5e1; }}
  .rep-table tbody tr:nth-child(even) {{ background: #f8fafc; }}
  .rep-table tfoot td {{
    font-weight: 700;
    border-top: 1px solid #94a3b8;
    border-bottom: 0;
  }}
  .rep-empty {{ color: #64748b; padding: 12px 0; }}
  .rep-note {{ margin-top: 16px; font-size: 10.5px; color: #64748b; }}
  @media print {{
    /* Scoped to the open report so a plain Ctrl+P on the canvas still prints
       the canvas. */
    body.report-open > *:not(#report-overlay) {{ display: none !important; }}
    body.report-open #report-overlay {{
      position: static;
      display: block;
      padding: 0;
      background: none;
    }}
    body.report-open .report-modal {{
      width: auto;
      max-height: none;
      border: 0;
      border-radius: 0;
      background: none;
    }}
    body.report-open .report-bar {{ display: none !important; }}
    body.report-open .report-scroll {{
      overflow: visible;
      padding: 0;
      background: none;
    }}
    body.report-open .report-sheet {{
      width: auto;
      min-width: 0;
      padding: 0;
      border-radius: 0;
    }}
    .rep-table thead {{ display: table-header-group; }}
    .rep-table tr {{ break-inside: avoid; }}
    @page {{ size: landscape; margin: 12mm; }}
  }}
  .toi-none {{ font-size: 12.5px; color: {props['axis-color']}; padding: 6px 0; }}
</style>
</head>
<body>
{self._scoreboard_html(back_href)}
<div class="layout">
  <div class="card rail">
    <div class="rail-head">
      <span class="section-heading">Metrics</span>
      <span class="spacer"></span>
      <button type="button" class="clear" id="rail-clear" onclick="_clearAll()">Clear</button>
    </div>
    <div class="rail-meta" id="rail-meta">{rail_meta}</div>
    <div class="search">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4.4" stroke="{props['axis-color']}" stroke-width="1.5"/><path d="M10.4 10.4 L14 14" stroke="{props['axis-color']}" stroke-width="1.5" stroke-linecap="round"/></svg>
      <input type="text" id="type-filter" placeholder="Filter metrics…" autocomplete="off" oninput="_filter(this.value)">
    </div>
    <div id="controls">
{rail_html}
    </div>
    <div class="rail-meta" id="no-match" hidden>No metrics match that filter.</div>
  </div>
  <div class="main">
    <div class="card timeline-card">
      <div class="card-head">
        <span class="section-heading">{props['title']}</span>
        <span class="head-right">{self._team_selector_html()}</span>
      </div>
{self._context_bar_html()}
      <div class="plot-wrap" id="plot-wrap" style="height: {plot_height}px">
{fig_html}
      </div>
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
  <div class="card roster">
    <div class="rail-head">
      <span class="section-heading">Players</span>
      <span class="spacer"></span>
      <button type="button" class="clear" id="roster-clear" onclick="_clearPlayers()">Clear</button>
    </div>
{self._player_mode_html()}
    <div class="rail-meta" id="roster-meta">all players</div>
{self._roster_html()}
  </div>
</div>
{self._report_html()}
<script>
var TOI_DATA = {json.dumps(toi_data)};
var TOI_NAMES = {json.dumps(toi_names)};
var TOI_POS = {json.dumps(toi_positions)};
var TOI_CEIL = {toi_ceiling};
var PLAYHEAD_SHAPE = {self._playhead_shape};
var PLAYHEAD_NOTE = {self._playhead_note};
var LANE_ORDER = {json.dumps(self._display_order)};
var SEGMENTS = {json.dumps(self._segments)};
var LANE_HALF = {_LANE_HALF};
var LANE_HEIGHT = {props['lane-height']};
var LANE_CHROME = {_LANE_CHROME};
var MIN_LANE_AREA = {_MIN_LANE_AREA};
var HEIGHT_AUTO = {json.dumps(props['height'] is None)};
var TEAM = '{_TEAM_BOTH}';
var PLAYERS = {{}};          // selected player ids; empty object = every player
var NUM_PLAYERS = 0;
var PLAYER_NAMES = {json.dumps(self._player_names_for_js())};
var ON_ICE = {json.dumps(self._on_ice_for_js())};
var PLAYER_MODE = 'player';   // 'player' = attributed to them, 'woi' = on ice
var WOI_SPANS = [];           // selected players' on-ice spans, merged
var DENSE_THRESHOLD = {_DENSE_THRESHOLD};
var HOME_NAME = {json.dumps(_team_label(self._game.info.home_team))};
var AWAY_NAME = {json.dumps(_team_label(self._game.info.away_team))};
var HOME_COLOR = {json.dumps(props['home-team-graph-color'])};
var AWAY_COLOR = {json.dumps(props['away-team-graph-color'])};
var NUM_TYPES = {num_types};
var PLAYER_META = {json.dumps(self._player_meta_for_js())};
var REPORT_INFO = {json.dumps(self._report_info())};
var REPORT = null;           // the model behind the sheet on screen
var _preSearchOpen = null;   // group open/closed state to restore after a search

// -- Context filter ---------------------------------------------------------
// Period, manpower and goalie situation, classified server-side by
// hockey/derive/context_filter.py and packed into one int per event:
//
//     code = period*100 + manpower*10 + goalies      (9 = the event cannot say)
//
// A selection is held as indices into those same tables, so filtering is
// integer comparison rather than string work on every one of ~16k memberships.
//
// Period's -1 is "All", which drops the constraint. Manpower and Goalies have
// no such value: ticking every button is how you get everything there, the
// same convention the metric rail uses.
var CTX_LABELS = {json.dumps({ctx.PERIOD: list(_CTX_PERIODS),
                              ctx.MANPOWER: list(_CTX_MANPOWER),
                              ctx.GOALIES: list(_CTX_GOALIES)})};
var CTX = {{"{ctx.PERIOD}": [-1], "{ctx.MANPOWER}": [0], "{ctx.GOALIES}": [0]}};
var CTX_UNKNOWN = {_CTX_UNKNOWN};

// An event the classifier could not place (code digit 9) matches no value, so
// it is dropped by any selection -- an unknown situation is not evidence of
// even strength.
function _ctxShown(seg, i) {{
  var code = seg.c[i];
  var per = CTX["{ctx.PERIOD}"];
  if (per.indexOf(-1) === -1 && per.indexOf((code / 100) | 0) === -1) return false;
  if (CTX["{ctx.MANPOWER}"].indexOf(((code / 10) | 0) % 10) === -1) return false;
  if (CTX["{ctx.GOALIES}"].indexOf(code % 10) === -1) return false;
  return true;
}}

function _setCtx(btn) {{
  var dim = btn.dataset.dim;
  var idx = parseInt(btn.dataset.idx, 10);
  var at = CTX[dim].indexOf(idx);
  if (at === -1) CTX[dim].push(idx); else CTX[dim].splice(at, 1);
  if (dim === "{ctx.PERIOD}") {{
    // "All" and the individual periods exclude each other, both ways.
    if (idx === -1 && at === -1) CTX[dim] = [-1];
    else if (idx !== -1) {{
      var allAt = CTX[dim].indexOf(-1);
      if (allAt !== -1) CTX[dim].splice(allAt, 1);
    }}
  }}
  // Emptying a dimension would blank the chart with no obvious way back, so
  // the last button out stays in.
  if (CTX[dim].length === 0) CTX[dim] = [idx];
  document.querySelectorAll('#ctx-bar .ctx').forEach(function(b) {{
    if (b.dataset.dim !== dim) return;
    b.classList.toggle('active',
      CTX[dim].indexOf(parseInt(b.dataset.idx, 10)) !== -1);
  }});
  _redraw();
}}

// One chip per dimension, for the bar and for the report sheet.
function _ctxChips() {{
  return ["{ctx.PERIOD}", "{ctx.MANPOWER}", "{ctx.GOALIES}"].map(function(dim) {{
    var names = CTX[dim].map(function(i) {{
      return i === -1 ? 'All' : CTX_LABELS[dim][i];
    }});
    return dim + ': ' + names.join(', ');
  }});
}}

function _updateCtxMeta() {{
  var el = document.getElementById('ctx-meta');
  if (el) el.textContent = _ctxChips().join('   ·   ');
}}

// A trace shows when its type is ticked AND it belongs to the selected team.
// "Both teams" keeps unattributed events; picking a team drops them, since
// they aren't that team's events. A segment belongs to exactly one side, so
// the team filter is decided per segment.
function _sideShown(side) {{
  return TEAM === '{_TEAM_BOTH}' || side === TEAM;
}}

// Merge the selected players' on-ice spans into one sorted, non-overlapping
// list, so "was anyone selected on the ice at t" is a binary search.
function _rebuildWoiSpans() {{
  var all = [];
  for (var pid in PLAYERS) {{
    if (PLAYERS[pid] !== true) continue;
    var spans = ON_ICE[pid];
    if (spans) spans.forEach(function(s) {{ all.push(s); }});
  }}
  all.sort(function(a, b) {{ return a[0] - b[0]; }});
  WOI_SPANS = [];
  all.forEach(function(s) {{
    var last = WOI_SPANS[WOI_SPANS.length - 1];
    if (last && s[0] <= last[1]) {{
      if (s[1] > last[1]) last[1] = s[1];
    }} else {{
      WOI_SPANS.push([s[0], s[1]]);
    }}
  }});
}}

function _onIceAt(t) {{
  var lo = 0, hi = WOI_SPANS.length - 1;
  while (lo <= hi) {{
    var mid = (lo + hi) >> 1;
    if (t < WOI_SPANS[mid][0]) hi = mid - 1;
    else if (t >= WOI_SPANS[mid][1]) lo = mid + 1;
    else return true;
  }}
  return false;
}}

// No players picked means "every player" -- the filter only narrows once at
// least one is selected. With players picked, "Player" keeps the events
// attributed to them; "Player WOI" keeps every event that happened while one
// of them was on the ice, whoever it is attributed to.
function _eventShown(seg, i) {{
  // Context first, and above the no-players shortcut below: the situation
  // filter applies whether or not anyone is selected, and "no players picked"
  // means every player, not every situation.
  if (!_ctxShown(seg, i)) return false;
  if (NUM_PLAYERS === 0) return true;
  var credited = PLAYERS[seg.p[i]] === true;
  // WOI also keeps anything credited to a selected player. Being credited
  // implies being on the ice, but ~2% of events (mostly faceoffs, a couple of
  // seconds before the recorded shift start) fall just outside the supplier's
  // own TOI interval -- without this, a player's own faceoff can vanish from
  // their WOI view, and WOI would not be a superset of Player.
  if (PLAYER_MODE === 'woi') return credited || _onIceAt(seg.t[i]);
  return credited;
}}

function _setPlayerMode(mode) {{
  if (mode === PLAYER_MODE) return;
  PLAYER_MODE = mode;
  document.querySelectorAll('#mode-sel .seg').forEach(function(btn) {{
    btn.classList.toggle('active', btn.dataset.mode === mode);
  }});
  _redraw();
}}

function _toggle(cb) {{
  _redraw();
}}

function _fmtCount(n) {{
  return String(n).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
}}

// How many events of a type survive the team, player AND context filters.
// This is what the rail shows, so its numbers always describe what the chart
// would draw -- including the dense flag.
//
// There used to be a shortcut here that added seg.t.length whole whenever no
// player was selected. That is no longer true of anything: the context filter
// narrows events with no player selected at all, so taking the shortcut would
// print unfiltered counts beside a filtered chart.
function _typeCount(type) {{
  var n = 0;
  SEGMENTS[type].forEach(function(seg) {{
    if (!_sideShown(seg.s)) return;
    for (var i = 0; i < seg.t.length; i++) {{
      if (_eventShown(seg, i)) n++;
    }}
  }});
  return n;
}}

function _updateTypeCounts() {{
  document.querySelectorAll('#controls .evt').forEach(function(row) {{
    var n = _typeCount(row.dataset.type);
    var cell = row.querySelector('.evt-count');
    cell.textContent = _fmtCount(n);
    cell.classList.toggle('dense', n >= DENSE_THRESHOLD);
  }});
}}

function _setTeam(side) {{
  if (side === TEAM) return;
  TEAM = side;
  document.querySelectorAll('#team-sel .seg').forEach(function(btn) {{
    btn.classList.toggle('active', btn.dataset.side === side);
  }});
  // Dim the roster of the team whose events are filtered out, so an empty
  // result reads as "excluded by the team filter" rather than as a bug.
  document.querySelectorAll('.team-block').forEach(function(block) {{
    block.classList.toggle('dimmed', !_sideShown(block.dataset.side));
  }});
  _redraw();
}}

function _togglePlayer(cb) {{
  var pid = cb.parentNode.dataset.pid;
  if (cb.checked) {{
    if (PLAYERS[pid] !== true) {{ PLAYERS[pid] = true; NUM_PLAYERS++; }}
  }} else if (PLAYERS[pid] === true) {{
    delete PLAYERS[pid];
    NUM_PLAYERS--;
  }}
  _rebuildWoiSpans();
  _redraw();
}}

function _clearPlayers() {{
  document.querySelectorAll('.plr input').forEach(function(b) {{ b.checked = false; }});
  PLAYERS = {{}};
  NUM_PLAYERS = 0;
  _rebuildWoiSpans();
  _redraw();
}}

function _updateRosterMeta() {{
  document.getElementById('roster-meta').textContent = NUM_PLAYERS
    ? NUM_PLAYERS + ' selected · ' +
      (PLAYER_MODE === 'woi' ? 'events while on ice' : 'events they are credited with')
    : 'all players';
  var clear = document.getElementById('roster-clear');
  if (clear) {{
    clear.style.color = NUM_PLAYERS ? HOME_COLOR : '#475569';
    clear.style.cursor = NUM_PLAYERS ? 'pointer' : 'default';
  }}
}}

function _visibleTypes() {{
  return LANE_ORDER.filter(function(t) {{
    var box = document.querySelector('.evt[data-type="' + t + '"] input');
    return box && box.checked;
  }});
}}

function _hoverText(type, t, pid, side) {{
  var text = type + ' — ' + _fmtTime(Math.round(t));
  if (side === 'h') text += ' · ' + HOME_NAME;
  else if (side === 'a') text += ' · ' + AWAY_NAME;
  var who = PLAYER_NAMES[pid];
  if (who) text += ' · ' + who;
  return text;
}}

// Single redraw path for all three filters. Ticked types get a lane each,
// packed with no gaps in rail order, so toggling one moves the lanes below it.
// Within a lane, x/y are rebuilt from the segment's event times, keeping only
// the events that pass the team and player filters -- a player filter can't be
// expressed as trace visibility, since one trace mixes every player.
function _redraw() {{
  var on = _visibleTypes();
  var shownIdx = [], xs = [], ys = [], texts = [];
  var hiddenIdx = [];
  var longest = 0;
  var lanes = {{}};

  on.forEach(function(type, lane) {{
    if (type.length > longest) longest = type.length;
    lanes[type] = lane;
  }});

  LANE_ORDER.forEach(function(type) {{
    var lane = lanes[type];
    var ticked = lane !== undefined;
    SEGMENTS[type].forEach(function(seg) {{
      if (!ticked || !_sideShown(seg.s)) {{
        hiddenIdx.push(seg.l, seg.h);
        return;
      }}
      var low = lane - LANE_HALF, high = lane + LANE_HALF;
      var lineX = [], lineY = [], markX = [], markY = [], hover = [];
      for (var i = 0; i < seg.t.length; i++) {{
        if (!_eventShown(seg, i)) continue;
        var t = seg.t[i];
        lineX.push(t, t, null);
        lineY.push(low, high, null);
        markX.push(t);
        markY.push(lane);
        hover.push(_hoverText(type, t, seg.p[i], seg.s));
      }}
      shownIdx.push(seg.l);
      xs.push(lineX); ys.push(lineY); texts.push([]);
      shownIdx.push(seg.h);
      xs.push(markX); ys.push(markY); texts.push(hover);
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
  // Height is driven by the wrapper, not by layout.height: the wrapper
  // reserves the space in the document flow, so a taller chart pushes the
  // cards below it down instead of drawing over them.
  if (HEIGHT_AUTO) {{
    var wrap = document.getElementById('plot-wrap');
    if (wrap) {{
      wrap.style.height =
        (LANE_CHROME + Math.max(MIN_LANE_AREA, n * LANE_HEIGHT)) + 'px';
    }}
  }}

  var gd = document.getElementById('{_DIV_ID}');
  if (hiddenIdx.length) {{
    Plotly.restyle(gd, {{visible: false}}, hiddenIdx);
  }}
  if (shownIdx.length) {{
    Plotly.update(gd, {{x: xs, y: ys, hovertext: texts, visible: true}},
                  layout, shownIdx);
  }} else {{
    Plotly.relayout(gd, layout);
  }}
  // Re-measure against the wrapper. Also corrects the width Plotly captured
  // mid-parse, before the roster pane narrowed this column.
  if (Plotly.Plots && Plotly.Plots.resize) {{
    Plotly.Plots.resize(gd);
  }}
  _updateCounts();
  _updateTypeCounts();
  _updateRosterMeta();
  _updateCtxMeta();
  _updateReportHint();
}}

// -- Report -----------------------------------------------------------------
// Built in the browser from what is already on the page (SEGMENTS, ON_ICE,
// PLAYER_META), so it needs no round trip and always tabulates exactly the
// selection the chart is drawing: the ticked types, the picked players, the
// team filter and the Player/WOI mode.

// Whether one player was on the ice at t. _onIceAt tests the merged spans of
// every selected player at once, which is what the chart needs; a per-player
// report has to ask about one player at a time.
function _onIceForPlayer(pid, t) {{
  var spans = ON_ICE[pid];
  if (!spans) return false;
  var lo = 0, hi = spans.length - 1;
  while (lo <= hi) {{
    var mid = (lo + hi) >> 1;
    if (t < spans[mid][0]) hi = mid - 1;
    else if (t >= spans[mid][1]) lo = mid + 1;
    else return true;
  }}
  return false;
}}

// [seconds on ice, shifts]. The spans are already merged, so supplier
// intervals that overlap are not counted twice.
function _playerToi(pid) {{
  var spans = ON_ICE[pid] || [];
  var total = 0;
  for (var i = 0; i < spans.length; i++) total += spans[i][1] - spans[i][0];
  return [Math.round(total), spans.length];
}}

function _fmtToi(s) {{
  var m = Math.floor(s / 60);
  var ss = s % 60;
  return m + ':' + (ss < 10 ? '0' : '') + ss;
}}

// PLAYER_META names are HTML-escaped for innerHTML; CSV wants them raw.
function _decode(html) {{
  var el = document.createElement('textarea');
  el.innerHTML = html;
  return el.value;
}}

// Selecting no players means "every player", as it does for the chart.
function _reportPlayerIds() {{
  var out = [];
  Object.keys(PLAYER_META).forEach(function(pid) {{
    if (!_sideShown(PLAYER_META[pid].s)) return;
    if (NUM_PLAYERS > 0 && PLAYERS[pid] !== true) return;
    out.push(pid);
  }});
  out.sort(function(a, b) {{
    var ma = PLAYER_META[a], mb = PLAYER_META[b];
    if (ma.s !== mb.s) return ma.s === 'h' ? -1 : 1;
    return (ma.n === '' ? 9999 : ma.n) - (mb.n === '' ? 9999 : mb.n);
  }});
  return out;
}}

function _reportModel() {{
  var metrics = _visibleTypes();
  var pids = _reportPlayerIds();
  var counts = {{}};
  pids.forEach(function(pid) {{
    counts[pid] = {{}};
    metrics.forEach(function(m) {{ counts[pid][m] = 0; }});
  }});

  metrics.forEach(function(type) {{
    SEGMENTS[type].forEach(function(seg) {{
      if (!_sideShown(seg.s)) return;
      for (var i = 0; i < seg.t.length; i++) {{
        // The report must tabulate exactly what the chart is drawing, and it
        // does not go through _eventShown -- WOI credits players who are not
        // the event's owner, which that function cannot express. So the
        // context test is repeated here rather than inherited.
        if (!_ctxShown(seg, i)) continue;
        var owner = seg.p[i];
        var credited = owner !== null && counts[owner] !== undefined;
        if (credited) counts[owner][type]++;
        if (PLAYER_MODE !== 'woi') continue;
        // WOI adds the events a player was on the ice for but is not credited
        // with; the credited one is skipped here so it is not counted twice.
        for (var j = 0; j < pids.length; j++) {{
          var pid = pids[j];
          if (credited && String(owner) === pid) continue;
          if (_onIceForPlayer(pid, seg.t[i])) counts[pid][type]++;
        }}
      }}
    }});
  }});

  var rows = [];
  pids.forEach(function(pid) {{
    var toi = _playerToi(pid);
    var total = 0;
    metrics.forEach(function(m) {{ total += counts[pid][m]; }});
    // With nobody picked the report covers the whole roster, scratches
    // included -- drop the rows that are empty in every column. A player the
    // user picked explicitly stays, so an all-zero row is still an answer.
    if (NUM_PLAYERS === 0 && total === 0 && toi[0] === 0) return;
    rows.push({{pid: pid, meta: PLAYER_META[pid], toi: toi[0],
               shifts: toi[1], counts: counts[pid], total: total}});
  }});
  return {{metrics: metrics, rows: rows}};
}}

function _repTable(metrics, rows) {{
  var head = '<tr><th class="l">#</th><th class="l">Player</th>' +
    '<th class="l">Pos</th><th>TOI</th><th>Shifts</th>' +
    metrics.map(function(m) {{ return '<th>' + m + '</th>'; }}).join('') +
    (metrics.length ? '<th>Total</th>' : '') + '</tr>';

  var body = rows.map(function(r) {{
    return '<tr><td class="l">' + r.meta.n + '</td>' +
      '<td class="l">' + r.meta.name + '</td>' +
      '<td class="l">' + r.meta.pos + '</td>' +
      '<td>' + _fmtToi(r.toi) + '</td>' +
      '<td>' + r.shifts + '</td>' +
      metrics.map(function(m) {{
        var v = r.counts[m];
        return '<td' + (v ? '' : ' class="zero"') + '>' + v + '</td>';
      }}).join('') +
      (metrics.length ? '<td>' + r.total + '</td>' : '') + '</tr>';
  }}).join('');

  var sums = metrics.map(function(m) {{
    return rows.reduce(function(a, r) {{ return a + r.counts[m]; }}, 0);
  }});
  var foot = '<tr><td class="l"></td><td class="l">Total</td><td></td>' +
    '<td>' + _fmtToi(rows.reduce(function(a, r) {{ return a + r.toi; }}, 0)) + '</td>' +
    '<td>' + rows.reduce(function(a, r) {{ return a + r.shifts; }}, 0) + '</td>' +
    sums.map(function(v) {{ return '<td>' + v + '</td>'; }}).join('') +
    (metrics.length
      ? '<td>' + sums.reduce(function(a, v) {{ return a + v; }}, 0) + '</td>' : '') +
    '</tr>';

  return '<table class="rep-table"><thead>' + head + '</thead><tbody>' +
    body + '</tbody><tfoot>' + foot + '</tfoot></table>';
}}

function _renderReport(model) {{
  var chips = [
    TEAM === 'both' ? 'Both teams' : (TEAM === 'h' ? HOME_NAME : AWAY_NAME),
    NUM_PLAYERS ? NUM_PLAYERS + ' players selected' : 'All players',
    PLAYER_MODE === 'woi' ? 'Events while on ice (WOI)'
                          : 'Events credited to the player',
    model.metrics.length
      ? model.metrics.length + (model.metrics.length === 1 ? ' metric' : ' metrics')
      : 'No metrics selected'
  ].concat(_ctxChips());

  var html = '<div class="rep-title">' + REPORT_INFO.title + '</div>' +
    '<div class="rep-meta">' + REPORT_INFO.meta + '</div>' +
    '<div class="rep-meta">Generated ' + new Date().toLocaleString() + '</div>' +
    '<div class="rep-filters">' +
      chips.map(function(c) {{ return '<span class="rep-chip">' + c + '</span>'; }}).join('') +
    '</div>';

  var tables = '';
  ['h', 'a'].forEach(function(side) {{
    var rows = model.rows.filter(function(r) {{ return r.meta.s === side; }});
    if (!rows.length) return;
    tables += '<div class="rep-team-head">' +
      '<i class="dot" style="background: ' +
        (side === 'h' ? HOME_COLOR : AWAY_COLOR) + '"></i>' +
      (side === 'h' ? HOME_NAME : AWAY_NAME) + '</div>' +
      _repTable(model.metrics, rows);
  }});
  html += tables || '<div class="rep-empty">' + (model.metrics.length
    ? 'No players match the current selection.'
    : 'Tick at least one event type in the rail to give the report columns.') +
    '</div>';

  if (PLAYER_MODE === 'woi' && model.metrics.length) {{
    html += '<div class="rep-note">WOI counts every event that happened while ' +
      'the player was on the ice, whoever it is credited to, so one event can ' +
      'appear on several rows and the column totals exceed the event count.</div>';
  }}
  return html;
}}

function _openReport() {{
  REPORT = _reportModel();
  document.getElementById('report-body').innerHTML = _renderReport(REPORT);
  document.getElementById('report-sub').textContent =
    REPORT.rows.length + (REPORT.rows.length === 1 ? ' player · ' : ' players · ') +
    REPORT.metrics.length + (REPORT.metrics.length === 1 ? ' metric' : ' metrics');
  document.getElementById('report-overlay').hidden = false;
  document.body.classList.add('report-open');
}}

function _closeReport() {{
  document.getElementById('report-overlay').hidden = true;
  document.body.classList.remove('report-open');
}}

function _backdrop(evt) {{
  if (evt.target.id === 'report-overlay') _closeReport();
}}

function _updateReportHint() {{
  var m = _visibleTypes().length;
  document.getElementById('report-hint').textContent =
    (NUM_PLAYERS ? NUM_PLAYERS + ' players' : 'all players') + ' × ' +
    m + (m === 1 ? ' metric' : ' metrics');
}}

function _downloadPdf() {{
  window.print();
}}

function _csvCell(v) {{
  v = String(v);
  return /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}}

function _downloadCsv() {{
  if (!REPORT) return;
  var m = REPORT.metrics;
  var header = ['Team', 'Number', 'Player', 'Position', 'TOI (s)', 'Shifts']
    .concat(m).concat(m.length ? ['Total'] : []);
  var lines = [header.map(_csvCell).join(',')];
  REPORT.rows.forEach(function(r) {{
    var cells = [r.meta.s === 'h' ? HOME_NAME : AWAY_NAME, r.meta.n,
                 _decode(r.meta.name), _decode(r.meta.pos), r.toi, r.shifts];
    m.forEach(function(k) {{ cells.push(r.counts[k]); }});
    if (m.length) cells.push(r.total);
    lines.push(cells.map(_csvCell).join(','));
  }});
  // BOM so Excel reads the UTF-8 in the player names.
  _saveFile(REPORT_INFO.slug + '.csv', 'text/csv;charset=utf-8',
            '﻿' + lines.join('\\n'));
}}

function _saveFile(name, mime, body) {{
  var url = URL.createObjectURL(new Blob([body], {{type: mime}}));
  var a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function() {{ URL.revokeObjectURL(url); }}, 0);
}}

function _updateCounts() {{
  var total = 0;
  document.querySelectorAll('#controls input[type=checkbox]').forEach(function(b) {{
    if (b.checked) total++;
  }});
  document.getElementById('rail-meta').textContent =
    NUM_TYPES + ' metrics in this game · ' + (total ? total + ' on chart' : 'none on chart');
  var clear = document.getElementById('rail-clear');
  clear.style.color = total ? HOME_COLOR : '#475569';
  clear.style.cursor = total ? 'pointer' : 'default';
  // Both levels carry a count. A module's own badge is the first .badge inside
  // it in DOM order (the one in its head), so this does not pick up a nested
  // group's badge instead.
  document.querySelectorAll('#controls .module, #controls .group').forEach(function(s) {{
    var on = s.querySelectorAll('input:checked').length;
    var badge = s.querySelector('.badge');
    if (!badge) return;
    badge.textContent = on + ' on';
    badge.hidden = (on === 0);
  }});
}}

function _toggleGroup(head) {{
  var g = head.parentNode;
  var open = g.classList.toggle('open');
  g.querySelector('.group-body').hidden = !open;
}}

function _toggleModule(head) {{
  var m = head.parentNode;
  var open = m.classList.toggle('open');
  m.querySelector('.module-body').hidden = !open;
}}

function _clearAll() {{
  document.querySelectorAll('#controls .evt input').forEach(function(b) {{
    b.checked = false;
  }});
  _redraw();
}}

// Hide a filter-group caption whose rows were all filtered away, so it cannot
// sit above rows that belong to the next caption.
function _syncCaptions(group) {{
  var body = group.querySelector('.group-body');
  if (!body) return;
  var caption = null, seen = false;
  Array.prototype.forEach.call(body.children, function(node) {{
    if (node.classList.contains('sub')) {{
      if (caption) caption.hidden = !seen;
      caption = node;
      seen = false;
    }} else if (!node.hidden) {{
      seen = true;
    }}
  }});
  if (caption) caption.hidden = !seen;
}}

// Search matches the FULL lane key ("Shots · On Net"), not just the visible
// item text, so typing a population name finds every metric under it. Both
// sides are lowercased: lane keys carry capitals now that they come from the
// metric modules, and a lowercased query against a mixed-case key would match
// nothing at all.
function _filter(q) {{
  q = q.trim().toLowerCase();
  var sections = document.querySelectorAll('#controls .module, #controls .group');
  // Remember how things were left before the first keystroke, so clearing the
  // box restores that rather than leaving everything expanded.
  if (q && _preSearchOpen === null) {{
    _preSearchOpen = [];
    sections.forEach(function(s) {{ _preSearchOpen.push(s.classList.contains('open')); }});
  }}
  var anyMatch = false;
  document.querySelectorAll('#controls .group').forEach(function(g) {{
    var shown = 0;
    g.querySelectorAll('.evt').forEach(function(row) {{
      var hit = !q || row.dataset.type.toLowerCase().indexOf(q) !== -1;
      row.hidden = !hit;
      if (hit) shown++;
    }});
    g.hidden = (shown === 0);
    if (shown) anyMatch = true;
    _syncCaptions(g);
  }});
  // A module is empty exactly when every population inside it is.
  document.querySelectorAll('#controls .module').forEach(function(m) {{
    var any = false;
    m.querySelectorAll('.group').forEach(function(g) {{ if (!g.hidden) any = true; }});
    m.hidden = !any;
  }});
  sections.forEach(function(s, i) {{
    var body = s.querySelector('.module-body') || s.querySelector('.group-body');
    if (!body) return;
    if (q) {{
      s.classList.add('open');
      body.hidden = false;
    }} else {{
      var was = _preSearchOpen ? _preSearchOpen[i] : s.classList.contains('open');
      s.classList.toggle('open', was);
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
  // Return to the filtered game list the user came from, as game.html does.
  var backLink = document.getElementById('back-link');
  var savedHome = sessionStorage.getItem('homeUrl');
  if (backLink && savedHome) backLink.href = savedHome;

  document.addEventListener('keydown', function(evt) {{
    if (evt.key === 'Escape') _closeReport();
  }});

  // Python renders the initial x/y, but hover text is built here so there is
  // only one implementation of the format -- so redraw once on load.
  _redraw();
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
