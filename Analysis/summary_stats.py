"""Aggregate the per-video BD metrics: averages per scenario, resolution, content class and QP,
plus scenario ranking and best/worst cases. Run bd_metrics.py first.

BD metrics are averaged with the arithmetic mean; EncT, being a time ratio, with the geometric mean (JVET reporting).

Usage:
    python summary_stats.py
    python summary_stats.py --suffix _vs_C5      # if bd_metrics.py was run with --anchor C5
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# Motion/texture labels are a qualitative first guess. Confirm them (e.g. with SI/TI, ITU-T P.910)
# before using them in the article, and edit here if needed.
VIDEO_INFO = pd.DataFrame(
    [
        ("BasketballDrill", "480p", "832x480", "C", "High", "Medium"),
        ("PartyScene", "480p", "832x480", "C", "Medium", "High"),
        ("FourPeople", "720p", "1280x720", "E", "Low", "Low"),
        ("CatRobot", "2160p", "3840x2160", "A2", "Medium", "High"),
        ("Tango2", "2160p", "3840x2160", "A1", "High", "Medium"),
    ],
    columns=["Video", "Resolution", "Size", "CTC class", "Motion", "Texture"],
)
ORDER = {"Resolution": ["480p", "720p", "2160p"], "Motion": ["Low", "Medium", "High"],
         "Texture": ["Low", "Medium", "High"]}
METRICS = ["BD-Rate (%)", "BD-PSNR (dB)", "EncT (%)"]
QP_METRICS = ["Bitrate change (%)", "PSNR change (dB)", "EncT (%)"]
RATIOS = {"EncT (%)"}


def geomean(values):
    return float(np.exp(np.log(values).mean()))


def averages(metrics):
    return {m: geomean if m in RATIOS else "mean" for m in metrics}


def mean_by(df, by, metrics=METRICS):
    out = df.groupby(by, observed=True)[metrics].agg(averages(metrics))
    if "Video" not in by:
        out.insert(0, "Videos", df.groupby(by, observed=True)["Video"].nunique())
    return out.reset_index()


def stats_by_scenario(df):
    out = df.groupby("Scenario")[METRICS].agg(["std", "min", "max"])
    out.columns = [f"{metric} {stat}" for metric, stat in out.columns]
    for metric, average in averages(METRICS).items():
        out.insert(out.columns.get_loc(f"{metric} std"), f"{metric} mean",
                   df.groupby("Scenario")[metric].agg(average))
    return out.reset_index()


def ranking(df):
    out = df.groupby("Scenario")[METRICS].agg(averages(METRICS))
    # Lower BD-Rate / higher BD-PSNR = better coding efficiency; lower EncT = faster.
    out["Rank BD-Rate"] = out["BD-Rate (%)"].rank(method="min").astype(int)
    out["Rank BD-PSNR"] = out["BD-PSNR (dB)"].rank(ascending=False, method="min").astype(int)
    out["Rank EncT"] = out["EncT (%)"].rank(method="min").astype(int)
    return out.sort_values("Rank BD-Rate").reset_index()


def best_worst(df):
    rows = []
    for scenario, g in df.groupby("Scenario"):
        for metric, lower_is_better in [("BD-Rate (%)", True), ("EncT (%)", True)]:
            best = g.loc[g[metric].idxmin() if lower_is_better else g[metric].idxmax()]
            worst = g.loc[g[metric].idxmax() if lower_is_better else g[metric].idxmin()]
            rows.append({
                "Scenario": scenario,
                "Metric": metric,
                "Best video": best["Video"],
                "Best value": best[metric],
                "Worst video": worst["Video"],
                "Worst value": worst[metric],
            })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resultsdir", type=Path, default=HERE / "results")
    parser.add_argument("--suffix", default="", help="output suffix used by bd_metrics.py, e.g. _vs_C5")
    opts = parser.parse_args()

    per_video = pd.read_csv(opts.resultsdir / f"bd_per_video{opts.suffix}.csv")
    per_qp = pd.read_csv(opts.resultsdir / f"per_qp{opts.suffix}.csv")

    missing = set(per_video["Video"]) - set(VIDEO_INFO["Video"])
    if missing:
        raise SystemExit(f"Add these videos to VIDEO_INFO: {sorted(missing)}")

    per_video = per_video.merge(VIDEO_INFO, on="Video")
    for col, order in ORDER.items():
        per_video[col] = pd.Categorical(per_video[col], categories=order, ordered=True)

    tables = {
        "by_scenario": stats_by_scenario(per_video),
        "by_resolution": mean_by(per_video, ["Scenario", "Resolution"]),
        "by_motion": mean_by(per_video, ["Scenario", "Motion"]),
        "by_texture": mean_by(per_video, ["Scenario", "Texture"]),
        "by_video": mean_by(per_video, ["Video"]),
        "by_qp": mean_by(per_qp, ["Scenario", "QP"], QP_METRICS),
        "scenario_ranking": ranking(per_video),
        "best_worst": best_worst(per_video),
    }

    for name, table in tables.items():
        path = opts.resultsdir / f"summary_{name}{opts.suffix}.csv"
        table.to_csv(path, index=False, float_format="%.4f")
        print(f"\n=== {name}  ->  {path.name}")
        print(table.to_string(index=False, float_format="%.3f"))

    print("\n=== Overall extremes (single scenario/video pairs)")
    for metric in METRICS:
        hi = per_video.loc[per_video[metric].idxmax()]
        lo = per_video.loc[per_video[metric].idxmin()]
        print(f"{metric:18s} max {hi[metric]:8.3f} ({hi['Scenario']}, {hi['Video']})"
              f"   min {lo[metric]:8.3f} ({lo['Scenario']}, {lo['Video']})")


if __name__ == "__main__":
    main()
