from __future__ import annotations
from pathlib import Path
import json
import matplotlib.pyplot as plt
from tqdm import tqdm
from hockey.config.settings import Settings
import numpy as np
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)

def current_shift_chances(data, teams=[], for_against_baseline="for", team_name=None):
    if teams == []:
        teams = list(data.keys())
    values = [np.asarray([v for v in data[str(team_id)][for_against_baseline]], dtype=float) for team_id in teams]
    values = np.concatenate(values)
    baseline = [np.asarray([v for v in data[str(team_id)]["baseline"]], dtype=float) for team_id in teams]
    baseline = np.concatenate(baseline)
    vmin, vmax = -40, 40
    w= 5.0
    left = -np.ceil(abs(vmin) / w) * w - w / 2
    right = np.ceil(abs(vmax) / w) * w + w / 2
    edges = np.arange(left, right + w, w)
    baseline_histogram = np.histogram(baseline, bins=edges)

    if for_against_baseline == "baseline":
        values_normalized = baseline_histogram[0] / len(teams)
        x_label = "DIFFERENCE IN AVERAGE TIME ON ICE DURING CURRENT SHIFT (5 vs 5, SHIFT RESET ON WHISTLE)"
        y_label = "SECONDS"
        y_min = 0
        y_max = 15000
    else:
        values_histogram = np.histogram(values, bins=edges)
        values_normalized = 1200 * values_histogram[0].astype(np.float32) / baseline_histogram[0].astype(np.float32) # Normalize to events per 20 minutes
        values_normalized = np.array(values_normalized)
        x_label ="DIFFERENCE IN AVERAGE TIME ON ICE DURING CURRENT SHIFT (5 vs 5, SHIFT RESET ON WHISTLE)"
        y_label = f"NUMBER OF A,B,C CHANCES {for_against_baseline.upper()}"
        y_min = 0
        y_max = 30
    fig, (ax1) = plt.subplots(1, 1, figsize=(12, 6), sharex=True)
    edges = np.array(edges)
    ax1.bar(edges[:-1] + w/2, values_normalized)
    ax1.axis([vmin - 2,vmax + 2,y_min,y_max])
    ax1.set_title("")
    plt.xlabel(x_label, fontweight="bold")
    plt.ylabel(y_label, fontsize=10, fontweight="bold")
    plt.tight_layout()
    ax1.text(-40, int(0.8*y_max), f'{team_name} ({for_against_baseline.upper()})', fontsize=20, color='blue', fontweight='bold')
    return fig, (ax1) #, ax2, ax3)


def generate_graphs_per_team():
    filepath = settings.output_path("abc_chances_5v5_1_20242025_regular.png")
    team_info = settings.data_path("teams.json")
    team_data= json.load(open(team_info.with_suffix('.json'), 'r'))
    data = json.load(open(filepath.with_suffix('.json'), 'r'))
    for team_id in tqdm(data.keys()):
        # if team_id != "200":
        #     continue
        team_id_data = [d for d in team_data['teams'] if d["id"] == team_id][0]
        team_name = team_id_data['location'] + " " + team_id_data['name']
        #print(team_id)
        for fab in ["baseline", "for", "against"]:
            fig, axes = current_shift_chances(data, [team_id], for_against_baseline=fab, team_name=team_name)
            #outfile = settings.output_path(f"abc_chances_5v5_1_{team_id}_{fab}").with_suffix('.png')
            outfile = settings.data_path("computed_stats","linhack26","shiftlength_team_performance","1", "width_5", f"abc_chances_5v5_1_{team_id}_{fab}").with_suffix('.png')
            fig.savefig(outfile)
            plt.close()

def generate_graphs_per_season():
    filepath = settings.output_path("abc_chances_5v5_13_20242025_regular.json")
    data = json.load(open(filepath.with_suffix('.json'), 'r'))
    for fab in ["for", "against", "baseline"]:
        fig, axes = current_shift_chances(data, [], for_against_baseline=fab, team_name="Team Average")
        outfile = settings.output_path(f"abc_chances_5v5_13_20242025_regular_all_teams_{fab}").with_suffix('.png')
        fig.savefig(outfile)
        plt.close()

if __name__ == "__main__":
    generate_graphs_per_team()
    #generate_graphs_per_season()
    # filepath = settings.output_path("abc_chances_5v5_13_20242025_regular.png")
    # team_info = settings.data_path("teams.json")
    # team_data= json.load(open(team_info.with_suffix('.json'), 'r'))
    # data = json.load(open(filepath.with_suffix('.json'), 'r'))
    #
    # for team_id in tqdm(data.keys()):
    #     # if team_id != "200":
    #     #     continue
    #     team_id_data = [d for d in team_data['teams'] if d["id"] == team_id][0]
    #     team_name = team_id_data['location'] + " " + team_id_data['name']
    #     #print(team_id)
    #     for fab in ["for", "against"]:
    #         fig, axes = current_shift_chances(data, [team_id], for_against_baseline=fab, team_name=team_name)
    #         outfile = settings.output_path(f"abc_chances_{team_id}_{fab}").with_suffix('.png')
    #         fig.savefig(outfile)
    #         plt.close()
