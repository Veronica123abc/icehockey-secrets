from __future__ import annotations
from pathlib import Path
import json

from cv2 import data
from tqdm import tqdm
from hockey.config.settings import Settings
import numpy as np
import matplotlib.pyplot as plt
from typing import Literal

Mode = Literal["for", "against", "baseline"]

settings = Settings.from_env(project_root=Path(__file__).resolve().parent)


def current_shift_chances(data: dict,
                          teams: list=[],
                          mode: Mode = "for",
                          label=None,
                          filter_type: str="A, B, C chances",):
    if teams == []:
        teams = list(data.keys())
    values = [np.asarray([v for v in data[str(team_id)][mode]], dtype=float) for team_id in teams]
    values = np.concatenate(values)
    baseline = [np.asarray([v for v in data[str(team_id)]["baseline"]], dtype=float) for team_id in teams]
    baseline = np.concatenate(baseline)
    vmin, vmax = -40, 40
    w= 5.0
    left = -np.ceil(abs(vmin) / w) * w - w / 2
    right = np.ceil(abs(vmax) / w) * w + w / 2
    edges = np.arange(left, right + w, w)
    baseline_histogram = np.histogram(baseline, bins=edges)

    if mode == "baseline":
        values_normalized = baseline_histogram[0] / len(teams)
        x_label = "DIFFERENCE IN AVERAGE TIME ON ICE DURING CURRENT SHIFT (5 vs 5, SHIFT RESET ON WHISTLE)"
        y_label = "SECONDS"
        y_min = 0
        y_max = max(values_normalized) + 1000 #120000
    else:
        values_histogram = np.histogram(values, bins=edges)
        values_normalized = 1200 * values_histogram[0].astype(np.float32) / baseline_histogram[0].astype(np.float32) # Normalize to events per 20 minutes
        values_normalized = np.array(values_normalized)
        x_label ="DIFFERENCE IN AVERAGE TIME ON ICE DURING CURRENT SHIFT (5 vs 5, SHIFT RESET ON WHISTLE)"
        y_label = f"NUMBER OF {filter_type.upper()} {mode.upper()}"
        y_min = 0
        y_max = 5 if filter_type=="goals" else 30
    fig, (ax1) = plt.subplots(1, 1, figsize=(12, 6), sharex=True)
    edges = np.array(edges)
    ax1.bar(edges[:-1] + w/2, values_normalized, width=w-2)
    ax1.axis([vmin - 2,vmax + 2,y_min,y_max])
    ax1.set_title("")
    plt.xlabel(x_label, fontweight="bold")
    plt.ylabel(y_label, fontsize=10, fontweight="bold")
    plt.tight_layout()
    ax1.text(-40, int(0.8*y_max), f'{label} ({mode.upper()})', fontsize=20, color='blue', fontweight='bold')
    return fig, (ax1) #, ax2, ax3)


def generate_graphs_per_team():
    filepath = settings.data_path("computed_stats/linhack26/shiftlength_team_performance/1",
                                  "filter_goal_5v5_1_20242025_regular.png")
    filepath = settings.output_path("filter_abc_5v5_13_20242025_regular_test.png")
    team_info = settings.data_path("teams.json")
    team_data= json.load(open(team_info.with_suffix('.json'), 'r'))
    data = json.load(open(filepath.with_suffix('.json'), 'r'))
    for team_id in tqdm(data.keys()):
        team_id_data = [d for d in team_data['teams'] if d["id"] == team_id][0]
        team_name = team_id_data['location'] + " " + team_id_data['name']
        for mode in ["baseline", "for", "against"]:
            fig, axes = current_shift_chances(data, [team_id], mode=mode, label=team_name, filter_type="abc")
            outfile = filepath.with_name(f"{filepath.stem}_{team_name}_{mode}.png")
            fig.savefig(outfile)
            plt.close()

def generate_graphs_per_season():
    #filepath = settings.output_path("abc_chances_5v5_13_20242025_regular.json")
    filepath = settings.data_path("computed_stats/linhack26/shiftlength_team_performance/1",
                                  "filter_abc_5v5_1_20242025_regular.json")
    data = json.load(open(filepath.with_suffix('.json'), 'r'))
    for mode in ["for", "against", "baseline"]:
        fig, axes = current_shift_chances(data, [], mode=mode, label=f"Team Average Regular Season 2024/25", filter_type="a/b/c chances")
        outfile = filepath.with_name(f"abc_5v5_13_20242025_regular_all_teams_{mode}").with_suffix('.png')
        fig.savefig(outfile)
        plt.close()

def average_team_season():
    filepath = settings.data_path("computed_stats/linhack26/shiftlength_team_performance/1",
                                  "filter_goal_5v5_1_20242025_regular.json")
    filepath_abc = settings.data_path("computed_stats/linhack26/shiftlength_team_performance/1",
                                  "filter_abc_5v5_1_20242025_regular.json")
    team_info = settings.data_path("teams.json")
    team_data= json.load(open(team_info.with_suffix('.json'), 'r'))
    data_goals = json.load(open(filepath.with_suffix('.json'), 'r'))
    data_abc = json.load(open(filepath_abc.with_suffix('.json'), 'r'))
    res = []
    av_abc = []
    fo_abc = []
    ag_abc = []
    av_goals = []
    fo_goals = []
    ag_goals = []

    for team_id in data_abc.keys():
        team_id_data = [d for d in team_data['teams'] if d["id"] == team_id][0]
        team_name = team_id_data['location'] + " " + team_id_data['name']
        #for mode in ["baseline"]:#, "for", "against"]:
        avg_goals = sum(data_goals[team_id]["baseline"]) / len(data_goals[team_id]["baseline"])
        num_for_goals = len(data_goals[team_id]["for"])
        num_against_goals = len(data_goals[team_id]["against"])
        avg_abc = sum(data_abc[team_id]["baseline"]) / len(data_goals[team_id]["baseline"])
        num_for_abc = len(data_abc[team_id]["for"])
        num_against_abc = len(data_abc[team_id]["against"])
        print(f"{team_name} {round(avg_goals, 2)} {num_for_goals} {num_against_goals}")
        av_goals.append(avg_goals)
        fo_goals.append(num_for_goals)
        ag_goals.append(num_against_goals)
        av_abc.append(avg_abc)
        fo_abc.append(num_for_abc)
        ag_abc.append(num_against_abc)

        #fig, axes = current_shift_chances(data, [team_id], mode=mode, label=team_name, filter_type="goals")
        #outfile = filepath.with_name(f"{filepath.stem}_{team_name}_{mode}.png")
        #fig.savefig(outfile)
        #lt.close()
    abc_diff = [f - a for f,a in zip(fo_abc,ag_abc)]
    goal_diff = [f - a for f,a in zip(fo_goals,ag_goals)]

    #plt.scatter(ag_abc, ag_goals)
    plt.scatter(abc_diff, goal_diff)
    plt.show()
if __name__ == "__main__":
    generate_graphs_per_team()
    #generate_graphs_per_season()
    #average_team_season()