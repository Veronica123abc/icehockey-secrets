from __future__ import annotations
from pathlib import Path
from hockey.model.game import Game
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
import os
import sys
import json
import matplotlib.pyplot as plt
from tqdm import tqdm
from typing import Any, Optional, TYPE_CHECKING
from hockey.config.settings import Settings
from hockey.io.raw_game import RawGame
from hockey.normalize.team_resolution import TeamResolver
from shifts import toi_status
import numpy as np
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
print(settings.data_root_dir, settings.output_dir)

import numpy as np

import numpy as np

def resample_hist_conv(values, factor):
    """
    Rebin symmetric histogram using box convolution + decimation.
    Zero bin remains centered.
    factor must be odd.
    """

    if factor % 2 == 0:
        raise ValueError("factor must be odd")

    values = np.asarray(values)
    n = len(values)

    center = n // 2
    half = factor // 2

    # Box kernel
    kernel = np.ones(factor, dtype=values.dtype)

    # Convolution (valid mode ensures full windows only)
    conv = np.convolve(values, kernel, mode='valid')

    # Index in conv corresponding to window centered at zero
    zero_index = center - half

    # Determine how many symmetric decimation steps fit
    max_k = zero_index // factor

    start = zero_index - max_k * factor
    end   = zero_index + max_k * factor + 1

    rebinned = conv[start:end:factor]

    return rebinned

def resample_hist(values, factor):
    if factor % 2 == 0:
        raise ValueError("factor must be odd to preserve symmetry around zero")

    values = np.asarray(values)
    n = len(values)
    center = n // 2
    half = factor // 2

    # maximum number of full windows on each side
    max_k = (center - half) // factor

    # start and end indices for symmetric truncation
    start = center - max_k * factor - half
    end = center + max_k * factor + half + 1

    trimmed = values[start:end]

    # reshape and sum
    new_values = trimmed.reshape(-1, factor).sum(axis=1)

    return new_values

def plot_baseline(data, team_id):
    values = data[str(team_id)]
    #plt.clf()
    #plt.hist(values, bins=20)
    #values = resample_hist(values, 5)

    values = resample_hist_conv(values, 1)

    plt.figure(figsize=(14, 4))
    plt.bar(range(len(values)), values, width=1.0, linewidth=0)
    #plt.xlim(0, min(len(values), 500))
    #plt.plot(values)
    plt.xlabel('time diff')
    plt.ylabel('#')
    #plt.show()
    #plt.savefig(settings.output_path(f"baseline_{team_id}.png"))
    return plt


def histogram_to_pdf(v, e):
    v = np.asarray(v)
    bin_widths = np.diff(e)
    total_area = np.sum(v * bin_widths)
    pdf = v / total_area
    return pdf

def pdf_to_cdf(pdf, e):
    bin_widths = np.diff(e)
    cdf = np.cumsum(pdf * bin_widths)
    return cdf

def sample_from_histogram(v, e, n_samples):
    v = np.asarray(v)
    e = np.asarray(e)

    # convert to PDF
    bin_widths = np.diff(e)
    total_area = np.sum(v * bin_widths)
    pdf = v / total_area

    # build CDF
    cdf = np.cumsum(pdf * bin_widths)

    # uniform random numbers
    u = np.random.rand(n_samples)

    # find bins
    bin_indices = np.searchsorted(cdf, u)

    # sample uniformly inside bins
    samples = e[bin_indices] + np.random.rand(n_samples) * bin_widths[bin_indices]

    return samples


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
