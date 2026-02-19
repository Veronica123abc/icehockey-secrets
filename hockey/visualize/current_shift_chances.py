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

def current_shift_chances(data, team_id, for_against_baseline="for"):
    teams = list(data.keys())

    values = []
    values_baseline = []
    values = []
    values = [np.asarray([v for v in data[str(team_id)][for_against_baseline]], dtype=float) for team_id in teams]
    values = np.concatenate(values)

    values_baseline = [np.asarray([v for v in data[str(team_id)]["baseline"]], dtype=float) for team_id in teams]
    values_baseline = np.concatenate(values_baseline)

    #values = np.asarray([round(v) for v in data[str(team_id)][for_against_baseline]], dtype=float)
    #values_baseline = np.asarray([round(v) for v in data[str(team_id)]["baseline"]], dtype=float)
    bins = 20
    vmin, vmax = -40, 40
    # bin width based on range / number of bins
    # w = (vmax - vmin) / bins if vmax > vmin else 1.0
    w= 5.0
    # build symmetric-ish edges around 0, ensuring 0 is a bin center
    left = -np.ceil(abs(vmin) / w) * w - w / 2
    right = np.ceil(abs(vmax) / w) * w + w / 2
    edges = np.arange(left, right + w, w)

    a = plt.hist(values, bins=edges)
    b = plt.hist(values_baseline, bins=edges)
    plt.cla()
    a_normalized = 1200 * a[0] / b[0] # Normalize to events per 20 minutes

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 6), sharex=True)

    a_normalized = np.array(a_normalized)
    edges = np.array(edges)
    ax1.bar(edges[:-1] + w/2, a_normalized)
    ax2.bar(edges[:-1] + w / 2, a[0])
    ax3.bar(edges[:-1] + w / 2, b[0])
    #plt.xlabel("time diff")
    #plt.ylabel("#")
    plt.tight_layout()
    return fig, (ax1, ax2, ax3)

if __name__ == "__main__":
    team_id = 200
    fab = "against"
    #filepath = settings.output_path("abc_chances_5v5_13_regular.json")
    filepath = settings.output_path("debug.json")

    # data = json.load(open(filepath.with_suffix('.json'), 'r'))
    # plt = plot_baseline(data, team_id)
    # p = filepath.with_name(filepath.stem + f"_{team_id}").with_suffix('.png')
    # plt.savefig(p)
    # #exit(0)

    #filepath = settings.output_path("abc_chances_5v5_13_regular.json")
    data = json.load(open(filepath.with_suffix('.json'), 'r'))
    #for team_id in data.keys():
    fig, axes = current_shift_chances(data, team_id, for_against_baseline=fab)
    outfile = filepath.with_name(filepath.stem + f"_all_teams_{fab}").with_suffix('.png')
    fig.savefig(outfile)
    #p= filepath.with_name(filepath.stem + f"_{team_id}_{fab}").with_suffix('.png')

    #plt.clf()