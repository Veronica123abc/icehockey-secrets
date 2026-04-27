from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from hockey.model.game import Game
from hockey.derive.entries import zone_entries, ZoneEntry

ENTRIES_VERSION = 1  # bump to invalidate cached entries HTML after visualization changes

ENTRY_COLORS = {
    "dumpin": "#60a5fa",
    "pass":   "#4ade80",
    "carry":  "#fb923c",
}

_BIN_EDGES = list(range(0, 31, 3))   # [0, 3, 6, ..., 30]
_BIN_LABELS = [f"{e}–{e+3}s" for e in _BIN_EDGES[:-1]]
_N_BINS = len(_BIN_LABELS)


def _first_shot_bins(entries: list[ZoneEntry]) -> dict[str, list[int]]:
    counts: dict[str, list[int]] = {t: [0] * _N_BINS for t in ENTRY_COLORS}
    for e in entries:
        if not e.shots:
            continue
        first = e.shots[0].time_since_entry
        if first >= 30:
            continue
        b = int(first // 3)
        if 0 <= b < _N_BINS:
            counts[e.entry_type][b] += 1
    return counts


def plot_entries(*, game: Game, filename: Optional[str] = "entries.html") -> go.Figure:
    entries = zone_entries(game)

    home = game.info.home_team
    away = game.info.away_team
    teams = [(home, entries[home.id]), (away, entries[away.id])]

    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"type": "pie"}, {"type": "pie"}], [{"type": "bar"}, {"type": "bar"}]],
        subplot_titles=[
            home.display_name,
            away.display_name,
            f"{home.display_name} — time to first shot",
            f"{away.display_name} — time to first shot",
        ],
        row_heights=[0.5, 0.5],
        vertical_spacing=0.14,
        horizontal_spacing=0.08,
    )

    for col, (team, team_entries) in enumerate(teams, start=1):
        # --- Pie chart: entry type distribution ---
        type_counts = {t: sum(1 for e in team_entries if e.entry_type == t) for t in ENTRY_COLORS}
        labels = [t for t in ENTRY_COLORS if type_counts[t] > 0]
        values = [type_counts[t] for t in labels]
        colors = [ENTRY_COLORS[t] for t in labels]
        total = sum(values)

        fig.add_trace(
            go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors, line=dict(color="#0f172a", width=2)),
                textinfo="label+percent",
                textfont=dict(color="#e2e8f0", size=13),
                hovertemplate="%{label}: %{value} entries (%{percent})<extra></extra>",
                hole=0.35,
                showlegend=False,
            ),
            row=1, col=col,
        )

        # Donut centre: total entry count
        fig.add_annotation(
            text=f"<b>{total}</b><br><span style='font-size:10px'>entries</span>",
            x=0.25 if col == 1 else 0.75,
            y=0.77,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(color="#94a3b8", size=13),
            align="center",
        )

        # --- Histogram: time from entry to first shot, stacked by type ---
        bins = _first_shot_bins(team_entries)
        for entry_type, counts in bins.items():
            if sum(counts) == 0:
                continue
            fig.add_trace(
                go.Bar(
                    x=_BIN_LABELS,
                    y=counts,
                    name=entry_type,
                    marker_color=ENTRY_COLORS[entry_type],
                    hovertemplate=f"{entry_type}: %{{y}}<extra></extra>",
                    showlegend=(col == 1),
                ),
                row=2, col=col,
            )

    for col in (1, 2):
        fig.update_xaxes(
            row=2, col=col,
            tickfont=dict(color="#64748b", size=10),
            gridcolor="#1e293b",
            linecolor="#334155",
            showline=False,
        )
        fig.update_yaxes(
            row=2, col=col,
            title_text="shots",
            titlefont=dict(color="#64748b"),
            tickfont=dict(color="#64748b"),
            gridcolor="#1e293b",
            zeroline=False,
            dtick=1,
        )

    for ann in fig.layout.annotations:
        ann.font.color = "#94a3b8"
        ann.font.size = 13

    fig.update_layout(
        title=dict(
            text=f"{home.display_name} vs {away.display_name} — Zone Entries",
            font=dict(color="#e2e8f0", size=16),
        ),
        barmode="stack",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#94a3b8"),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(color="#94a3b8"),
            bgcolor="rgba(0,0,0,0)",
        ),
        height=750,
        margin=dict(t=80, b=40, l=60, r=20),
    )

    if filename is not None:
        fig.write_html(filename, auto_open=False)
    return fig


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

    fig = plot_entries(game=game, filename="entries.html")
    print("Written to entries.html")
