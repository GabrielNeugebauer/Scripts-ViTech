"""Per-video BD-Rate, BD-PSNR and encoding time ratio (EncT) of each scenario against the anchor.

EncT follows the JVET reporting: test time / anchor time x 100, so values below 100% are faster than the
anchor. The value of each video is the geometric mean of the ratios of its QPs.

Usage:
    python bd_metrics.py                         # data/relatorio_final.csv, anchor C0, pchip
    python bd_metrics.py --anchor C5             # e.g. measure each tool against "no tools"
    python bd_metrics.py --method akima
"""

import argparse
from pathlib import Path

import bjontegaard as bd
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
QP_COUNT = 4


def geomean(values):
    return float(np.exp(np.log(values).mean()))


def compute(df, anchor, method):
    per_video, per_qp = [], []

    for video, df_video in df.groupby("Video"):
        base = df_video[df_video["Scenario"] == anchor]
        if len(base) < QP_COUNT:
            print(f"Skipping {video}: anchor {anchor} has {len(base)} points, needs {QP_COUNT}.")
            continue

        for scenario, test in df_video[df_video["Scenario"] != anchor].groupby("Scenario"):
            # Pair anchor and test runs by QP so EncT compares the same encoding point.
            m = base.merge(test, on="QP", suffixes=("_a", "_t")).sort_values("QP")
            if len(m) < QP_COUNT:
                print(f"Skipping {scenario}/{video}: only {len(m)} QPs match the anchor.")
                continue

            args = (m["Bitrate_a"], m["PSNR-YUV_a"], m["Bitrate_t"], m["PSNR-YUV_t"])
            enc_t = m["Execution time_t"] / m["Execution time_a"] * 100

            per_video.append({
                "Scenario": scenario,
                "Video": video,
                "BD-Rate (%)": bd.bd_rate(*args, method=method),
                "BD-PSNR (dB)": bd.bd_psnr(*args, method=method),
                "EncT (%)": geomean(enc_t),
            })

            per_qp.append(pd.DataFrame({
                "Scenario": scenario,
                "Video": video,
                "QP": m["QP"],
                "Bitrate change (%)": (m["Bitrate_t"] / m["Bitrate_a"] - 1) * 100,
                "PSNR change (dB)": m["PSNR-YUV_t"] - m["PSNR-YUV_a"],
                "EncT (%)": enc_t,
            }))

    per_video = pd.DataFrame(per_video).sort_values(["Video", "Scenario"], ignore_index=True)
    per_qp = pd.concat(per_qp).sort_values(["Video", "Scenario", "QP"], ignore_index=True)
    return per_video, per_qp


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=HERE / "data" / "relatorio_final.csv")
    parser.add_argument("--outdir", type=Path, default=HERE / "results")
    parser.add_argument("--anchor", default="C0")
    parser.add_argument("--method", default="pchip", choices=["pchip", "akima", "cubic"],
                        help="pchip matches the JVET CTC Excel sheet (default)")
    opts = parser.parse_args()

    df = pd.read_csv(opts.input)
    per_video, per_qp = compute(df, opts.anchor, opts.method)

    opts.outdir.mkdir(parents=True, exist_ok=True)
    suffix = "" if opts.anchor == "C0" else f"_vs_{opts.anchor}"
    per_video_path = opts.outdir / f"bd_per_video{suffix}.csv"
    per_qp_path = opts.outdir / f"per_qp{suffix}.csv"
    per_video.to_csv(per_video_path, index=False, float_format="%.4f")
    per_qp.to_csv(per_qp_path, index=False, float_format="%.4f")

    print(f"Anchor: {opts.anchor} | interpolation: {opts.method}\n")
    print(per_video.to_string(index=False, float_format="%.3f"))
    print(f"\nSaved {per_video_path}\nSaved {per_qp_path}")


if __name__ == "__main__":
    main()
