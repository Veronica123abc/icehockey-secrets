import json
import mpld3
import matplotlib.patches as mpatches
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from collections import defaultdict
import db_tools
import dotenv
import os
import ingest
import pandas as pd
import plotly.graph_objs as go
import plotly.offline as pyo
import cv2
import io
import base64
# import entries
#from generate_entry_statistics import stats_db
import apiv2
import numpy as np

dotenv.load_dotenv()
DATA_ROOT = os.getenv("DATA_ROOT")

def create_interactive_line_plot(): #home_wp, away_wp, home_chances, away_chances, filename='hockey_visual3.html'):

    team_strengths=[]
    # Interpolate all intermediate values for the two teams
    for team_wp in [home_wp, away_wp]:
        length = len(team_wp)
        times, values = zip(*team_wp)
        full_time = np.arange(length)
        team_strengths.append(np.interp(full_time, times, values))
    home_strength = team_strengths[0] #  interpolate_strength(home_wp)
    away_strength = team_strengths[1] # interpolate_strength(away_wp)
    game_duration = len(home_wp)
    x = np.arange(game_duration)

    home_y_offsets = [0.0, 10.0, 20.0, 30.0]
    away_y_offsets = [0.0, 10.0, 20.0, 30.0]

    home_team_color = 'blue'
    away_team_color = 'red'
    difference_color = 'black'
    text_color = 'white'
    flag_color = 'black'
    flag_edge = 'white'
    scatter_disc_size = 50
    scatter_text_size = 5
    rendered_height=1000
    # Calculate y-positions for flags using cycling offsets
    home_flag_ys = [max(home_strength) + home_y_offsets[i % len(home_y_offsets)] for i in range(len(home_chances))]
    away_flag_ys = [-max(away_strength) - away_y_offsets[i % len(away_y_offsets)] for i in range(len(away_chances))]

    # Line plots for strengths
    home_trace = go.Scatter(x=x, y=home_strength, mode='lines', name='Home Team', line=dict(color=home_team_color, width=2))
    away_trace = go.Scatter(x=x, y=-away_strength, mode='lines', name='Away Team', line=dict(color=away_team_color, width=2))
    diff_trace = go.Scatter(x=x, y=home_strength - away_strength, mode='lines', name='Difference', line=dict(color=difference_color, width=4))

    # Vertical lines for home_chances
    shapes = []
    for (t, _), y in zip(home_chances, home_flag_ys):
        shapes.append(dict(
            type='line',
            #ysizemode='pixel',
            x0=t, x1=t,
            y0=0, y1=y-2,#rendered_height/(scatter_disc_size),
            #x=t,
            #y=100,
            line=dict(color='orange', width=4, dash='solid'),
            layer="below",
        ))

    # Vertical lines for away chances
    for (t, _), y in zip(away_chances, away_flag_ys):
        shapes.append(dict(
            type='line',
            x0=t, x1=t,
            y0=y, y1=0,
            line=dict(color='orange', width=2, dash='solid'),
            layer="below",
        ))

    # for x,y in zip([t for t, _ in home_chances], home_flag_ys):
    #     shapes.append(dict(
    #         type="circle",
    #         x0=x - scatter_disc_size, x1=x + scatter_disc_size,
    #         y0=y - scatter_disc_size, y1=y + scatter_disc_size,
    #         line=dict(color="RoyalBlue"),
    #         fillcolor="LightSkyBlue",
    #         opacity=0.5
    #         )
    #     )

    home_flags = go.Scatter(
        x=[t for t, _ in home_chances],
        y=home_flag_ys,
        #y=[max(home_strength) + 0.5] * len(home_chances),
        mode='markers+text',
        marker=dict(size=scatter_disc_size, color=flag_color, line=dict(width=scatter_text_size, color=home_team_color)),
        text=[c for _, c in home_chances],
        textposition='middle center',
        textfont=dict(size=30,color=text_color),
        showlegend=False
    )

    away_flags = go.Scatter(
        x=[t for t, _ in away_chances],
        y=away_flag_ys,
        #y=[-max(away_strength) - 0.5] * len(away_chances),
        mode='markers+text',
        marker=dict(size=scatter_disc_size, color=flag_color, line=dict(width=scatter_text_size, color=away_team_color)),
        text=[c for _, c in away_chances],
        textposition='middle center',
        textfont=dict(size=30,color=text_color),
        showlegend=False
    )



    # # Vertical lines for home chances
    # for (t, _), y in zip(home_chances, home_flag_ys):
    #     shapes.append(dict(
    #         type='line',
    #         x0=t, x1=t,
    #         y0=0, y1=y,
    #         line=dict(color='orange', width=2, dash='solid')
    #     ))
    #
    # # Vertical lines for away chances
    # for (t, _), y in zip(away_chances, away_flag_ys):
    #     shapes.append(dict(
    #         type='line',
    #         x0=t, x1=t,
    #         y0=y, y1=0,
    #         line=dict(color='orange', width=2, dash='solid')
    #     ))

    layout = go.Layout(
        title='Average Time on Ice and Scoring Chances',
        xaxis=dict(title='Time (seconds)', range=[0, game_duration]),
        yaxis=dict(title='Average TOI for players on ice'),
        showlegend=True,
        height=rendered_height,
        shapes=shapes
    )

    fig = go.Figure(data=[home_trace, away_trace, diff_trace, home_flags, away_flags], layout=layout)
    #fig = go.Figure(data=[home_trace, away_trace, diff_trace], layout=layout)
    pyo.plot(fig, filename=filename, auto_open=False)
    return fig