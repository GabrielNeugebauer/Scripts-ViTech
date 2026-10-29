"""Decoding time ratio (DecT) of each scenario against the anchor, from the output of run_vtm_decoder.py.

DecT follows the JVET reporting: test time / anchor time x 100, so values below 100% decode faster than the
anchor. Each bitstream is decoded several times (Run column) and the mean of the runs is used for each point.
The value of each video is the geometric mean over its QPs; averages over videos are geometric means too.

Usage:
    python decode_metrics.py                     # data/tempos_decodificacao.csv, anchor C0
    python decode_metrics.py --anchor C5
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KEYS = ["Scenario", "Video", "QP"]


def geomean(values):
    return float(np.exp(np.log(values).mean()))


def compute(df, anchor):
    ok = df[df["Status"] == "Sucesso"]
    points = ok.groupby(KEYS)["Decoding time"].agg(["mean", "std", "count"]).reset_index()
    points["CV (%)"] = points["std"] / points["mean"] * 100

    base = points[points["Scenario"] == anchor][["Video", "QP", "mean"]]
    m = points[points["Scenario"] != anchor].merge(base, on=["Video", "QP"], suffixes=("", "_a"))
    m["DecT (%)"] = m["mean"] / m["mean_a"] * 100
    per_qp = m.rename(columns={"mean": "Decoding time (s)", "mean_a": "Anchor decoding time (s)", "count": "Runs"})
    per_qp = per_qp[KEYS + ["Runs", "Decoding time (s)", "Anchor decoding time (s)", "CV (%)",
                            "DecT (%)"]].sort_values(KEYS, ignore_index=True)

    per_video = (per_qp.groupby(["Scenario", "Video"])["DecT (%)"].agg(geomean)
                 .reset_index().sort_values(["Video", "Scenario"], ignore_index=True))

    summary = per_video.groupby("Scenario")["DecT (%)"].agg(
        **{"DecT (%)": geomean, "Min (%)": "min", "Max (%)": "max"}).reset_index()
    return per_qp, per_video, summary, points


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=HERE / "data" / "tempos_decodificacao.csv")
    parser.add_argument("--outdir", type=Path, default=HERE / "results")
    parser.add_argument("--anchor", default="C0")
    opts = parser.parse_args()

    df = pd.read_csv(opts.input)
    failed = df[df["Status"] != "Sucesso"]
    if len(failed):
        print(f"Ignoring {len(failed)} failed decodings.")

    per_qp, per_video, summary, points = compute(df, opts.anchor)

    opts.outdir.mkdir(parents=True, exist_ok=True)
    suffix = "" if opts.anchor == "C0" else f"_vs_{opts.anchor}"
    outputs = {
        f"decoding_per_qp{suffix}.csv": per_qp,
        f"decoding_per_video{suffix}.csv": per_video,
        f"decoding_summary{suffix}.csv": summary,
    }
    for name, table in outputs.items():
        table.to_csv(opts.outdir / name, index=False, float_format="%.4f")

    # Run-to-run variation: a check on the measurements, not a reported metric
    print(f"Anchor: {opts.anchor} | runs per bitstream: {points['count'].min()}-{points['count'].max()}")
    print(f"Run-to-run CV: median {points['CV (%)'].median():.2f}%, max {points['CV (%)'].max():.2f}%\n")
    table = per_video.pivot(index="Video", columns="Scenario", values="DecT (%)")
    table.loc["Average"] = summary.set_index("Scenario")["DecT (%)"]
    print(table.to_string(float_format="%.2f"), "\n")
    print(summary.to_string(index=False, float_format="%.2f"))
    print("\n" + "\n".join(f"Saved {opts.outdir / name}" for name in outputs))


if __name__ == "__main__":
    main()
