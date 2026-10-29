"""Article figures from the results of bd_metrics.py. Saves PNGs (300 dpi) to results/."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

SCENARIOS = {"C1": "No PROF", "C2": "No Affine/PROF", "C3": "No BDOF", "C4": "Affine only", "C5": "No tools"}
VIDEOS = ["BasketballDrill", "PartyScene", "FourPeople", "CatRobot", "Tango2"]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def geomean(values):
    return float(np.exp(np.log(values).mean()))

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
    "font.size": 9,
    "axes.edgecolor": INK_2,
    "axes.labelcolor": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "legend.frameon": False,
})


def bd_rate_per_video(per_video):
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    width = 0.16
    for i, (video, color) in enumerate(zip(VIDEOS, COLORS)):
        values = per_video[per_video["Video"] == video].set_index("Scenario").loc[list(SCENARIOS), "BD-Rate (%)"]
        x = [s + (i - 2) * width for s in range(len(SCENARIOS))]
        ax.bar(x, values, width, color=color, edgecolor="white", linewidth=0.8, label=video)
    ax.set_xticks(range(len(SCENARIOS)), [f"{k}\n{v}" for k, v in SCENARIOS.items()])
    ax.set_ylabel("BD-Rate (%) vs. C0")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.14), handlelength=1, columnspacing=1.2)
    return fig


def tradeoff(per_video):
    mean = per_video.groupby("Scenario").agg({"BD-Rate (%)": "mean", "EncT (%)": geomean})
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    ax.grid(True, axis="both")
    ax.axhline(100, color=INK_2, linewidth=0.8)
    ax.scatter(mean["BD-Rate (%)"], mean["EncT (%)"], s=40, color=COLORS[0],
               edgecolor="white", linewidth=1, zorder=3)
    for scenario, row in mean.iterrows():
        offset = (6, -11) if scenario == "C3" else (6, 4)
        ax.annotate(f"{scenario} ({SCENARIOS[scenario]})", (row["BD-Rate (%)"], row["EncT (%)"]),
                    xytext=offset, textcoords="offset points", color=INK)
    ax.set_xlim(0, mean["BD-Rate (%)"].max() * 1.35)
    ax.set_ylim(mean["EncT (%)"].min() - 3, max(mean["EncT (%)"].max(), 100) + 3)
    ax.set_xlabel("Average BD-Rate (%) vs. C0 (lower is better)")
    ax.set_ylabel("EncT (%) vs. C0 (lower is faster)")
    return fig


def enc_t_per_qp(per_qp):
    mean = per_qp.groupby(["Scenario", "QP"])["EncT (%)"].agg(geomean).unstack("Scenario")
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    ax.axhline(100, color=INK_2, linewidth=0.8)
    for scenario, color in zip(SCENARIOS, COLORS):
        ax.plot(mean.index, mean[scenario], color=color, linewidth=1.6, marker="o", markersize=4,
                markeredgecolor="white", label=f"{scenario} ({SCENARIOS[scenario]})")
    ax.set_xticks(mean.index)
    ax.set_xlabel("QP")
    ax.set_ylabel("EncT (%) vs. C0 (lower is faster)")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5))
    return fig


def main():
    per_video = pd.read_csv(RESULTS / "bd_per_video.csv")
    per_qp = pd.read_csv(RESULTS / "per_qp.csv")
    figures = {
        "fig_bd_rate_per_video.png": bd_rate_per_video(per_video),
        "fig_tradeoff.png": tradeoff(per_video),
        "fig_enc_t_per_qp.png": enc_t_per_qp(per_qp),
    }
    for name, fig in figures.items():
        fig.savefig(RESULTS / name, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"Saved {RESULTS / name}")


if __name__ == "__main__":
    main()
