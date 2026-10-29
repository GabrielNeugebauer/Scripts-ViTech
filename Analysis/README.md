# VVC inter-prediction tools: analysis scripts

Scripts that turn the VTM results into the BD metrics, summary tables and figures of the article on Affine, PROF and BDOF (`Artigo VVC - completo v2.docx`). The input data is in `data/`; the outputs go to `results/`, which git ignores.

```
data/relatorio_final.csv          (encoder results, one row per encoding)
  └─ bd_metrics.py      → results/bd_per_video.csv, results/per_qp.csv
       ├─ summary_stats.py  → results/summary_*.csv
       └─ make_figures.py   → results/fig_*.png

data/tempos_decodificacao.csv     (from ../VTM/run_vtm_decoder.py)
  └─ decode_metrics.py  → results/decoding_*.csv
```

## Setup

Run everything from this folder (`Analysis/`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3 (3.12.3 was used) and `bjontegaard` 1.3 or later, whose `bd_rate`/`bd_psnr` take a required `method` argument.

## Quick start

```bash
python bd_metrics.py       # BD metrics and EncT, anchor C0
python summary_stats.py    # averages, rankings, best/worst cases
python make_figures.py     # the 3 article figures
python decode_metrics.py   # DecT (Section 4.5, Table 7)
```

To measure each tool's gain over a codec without the tools (Section 4.1 of the article), also run:

```bash
python bd_metrics.py --anchor C5
python summary_stats.py --suffix _vs_C5
```

## Input: `data/relatorio_final.csv`

One row per encoding: 6 scenarios × 5 videos × 4 QPs = 120 rows.

| Column           | Meaning                                 |
| ---------------- | --------------------------------------- |
| `Scenario`       | `C0`–`C5` (see below)                   |
| `Video`          | Sequence name, e.g. `CatRobot`          |
| `QP`             | 22, 27, 32 or 37                        |
| `PSNR-YUV`       | Combined YUV PSNR reported by VTM (dB)  |
| `Bitrate`        | Bitrate reported by VTM (kbps)          |
| `Execution time` | Total encoding time reported by VTM (s) |

| Scenario    | Affine | PROF | BDOF |
| ----------- | ------ | ---- | ---- |
| C0 (anchor) | on     | on   | on   |
| C1          | on     | off  | on   |
| C2          | off    | off  | on   |
| C3          | on     | on   | off  |
| C4          | on     | off  | off  |
| C5          | off    | off  | off  |

## `bd_metrics.py`

For each video, compares every scenario with the anchor, pairing the runs by QP.

- **BD-Rate (%)**: average bitrate difference at equal PSNR. Positive = loss (more bits needed).
- **BD-PSNR (dB)**: average PSNR difference at equal bitrate. Negative = loss.
- **EncT (%)**: encoding time ratio, as reported by JVET: `T_scenario / T_anchor × 100`, computed per QP. Below 100% = faster than the anchor. The value of each video is the **geometric mean** over its QPs.

A video is skipped, with a message, if the anchor or the scenario doesn't have all 4 QPs.

| Option     | Default               | Description                                                                   |
| ---------- | --------------------- | ----------------------------------------------------------------------------- |
| `--input`  | `data/relatorio_final.csv` | Input CSV                                                                |
| `--outdir` | `results/`            | Output folder                                                                 |
| `--anchor` | `C0`                  | Reference scenario                                                            |
| `--method` | `pchip`               | Interpolation: `pchip` (matches the JVET CTC Excel sheet), `akima` or `cubic` |

Outputs (the suffix `_vs_<anchor>` is added when the anchor isn't C0):

- `bd_per_video.csv`: `Scenario, Video, BD-Rate (%), BD-PSNR (dB), EncT (%)`
- `per_qp.csv`: `Scenario, Video, QP, Bitrate change (%), PSNR change (dB), EncT (%)`

## `summary_stats.py`

BD metrics are averaged with the arithmetic mean and EncT with the geometric mean, as in the JVET reporting. It reads the outputs of `bd_metrics.py` and adds the per-video metadata in `VIDEO_INFO` (resolution, size, CTC class, motion, texture). It stops with an error if a video in the results is missing from `VIDEO_INFO`.

| Option         | Default    | Description                                   |
| -------------- | ---------- | --------------------------------------------- |
| `--resultsdir` | `results/` | Folder with the `bd_metrics.py` outputs       |
| `--suffix`     | (empty)    | Same suffix as `bd_metrics.py`, e.g. `_vs_C5` |

Outputs, all in `results/` as `summary_<name><suffix>.csv`:

| File                                      | Content                                                                        |
| ----------------------------------------- | ------------------------------------------------------------------------------ |
| `summary_by_scenario`                     | Mean, std, min and max of each metric per scenario (Table 3)                   |
| `summary_by_resolution`                   | Means per scenario and resolution (Table 6)                                    |
| `summary_by_motion`, `summary_by_texture` | Means per scenario and content class                                           |
| `summary_by_video`                        | Means per video over all scenarios                                             |
| `summary_by_qp`                           | Bitrate change, PSNR change and EncT per scenario and QP (Section 4.4) |
| `summary_scenario_ranking`                | Mean metrics and rank of each scenario (rank 1 = best)                         |
| `summary_best_worst`                      | Best and worst video of each scenario, for BD-Rate and EncT            |

It also prints the overall extremes (single scenario/video pairs) of each metric.

The `Motion` and `Texture` labels in `VIDEO_INFO` are a qualitative first guess and are not used in the article. Confirm them, for example with SI/TI (ITU-T P.910), before using them.

## `make_figures.py`

Draws the article figures with matplotlib from `results/bd_per_video.csv` and `results/per_qp.csv` (anchor C0 only). Saves PNGs at 300 dpi in `results/`, using a Times-like serif font to match the article.

| File                          | Article figure | Chart                                                               |
| ----------------------------- | -------------- | ------------------------------------------------------------------- |
| `fig_tradeoff.png`            | Figure 1       | Scatter plot: average BD-Rate vs. average EncT per scenario |
| `fig_bd_rate_per_video.png`   | Figure 2       | Grouped bars: BD-Rate per scenario, one bar per video               |
| `fig_enc_t_per_qp.png`        | Figure 3       | Lines: average EncT per QP, one line per scenario                   |

It takes no options. The scenario names, video order and colors are set at the top of the script (`SCENARIOS`, `VIDEOS`, `COLORS`).

After regenerating the figures, replace the images in the `.docx` by hand (right-click the image → Replace).

## `decode_metrics.py`

Reads `data/tempos_decodificacao.csv`, written by `../VTM/run_vtm_decoder.py` (copy it here from the decoder's `decoder_reports_dir`). It has one row per decoding run, with the columns `Scenario, Video, QP, Run, Decoding time, Wall time, Frames, Status, Bitstream, Date`. Rows whose `Status` isn't `Sucesso` are ignored.

For each scenario/video/QP it averages the runs of `Decoding time` (the "Total Time" printed by the VTM decoder) and computes the **decoding time ratio (DecT)** against the anchor with the same formula as EncT: `T_scenario / T_anchor × 100`. Below 100% = decodes faster than the anchor. Values per video and averages are geometric means.

| Option     | Default                    | Description        |
| ---------- | -------------------------- | ------------------ |
| `--input`  | `data/tempos_decodificacao.csv` | Decoding times CSV |
| `--outdir` | `results/`                 | Output folder      |
| `--anchor` | `C0`                       | Reference scenario |

Outputs (suffix `_vs_<anchor>` when the anchor isn't C0):

| File                     | Content                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| `decoding_per_qp.csv`    | Mean decoding time, anchor time, run-to-run CV and DecT per scenario, video and QP      |
| `decoding_per_video.csv` | DecT per scenario and video, geometric mean over the QPs (Table 7)                            |
| `decoding_summary.csv`   | Average DecT (geometric mean over the videos), min and max per scenario |

It also prints the run-to-run coefficient of variation (CV), which shows how stable the repeated runs were. It is a check on the measurements, not a reported metric.

## Notes

- The article reports two decimal places. The CSVs keep four.
- The encoding times come from a single run per configuration, with several encodings running in parallel. Small differences in EncT (a few %) are within measurement noise. See Section 4.6 of the article.
- The decoding times come from three runs per bitstream, but the decodings also ran in parallel (about 120 at a time). Decode one bitstream at a time for cleaner timings.
- To analyze other data, pass `--input` (and `--outdir`) instead of replacing the files in `data/`.
- If you add videos or QPs, update `VIDEO_INFO` in `summary_stats.py` and `VIDEOS` in `make_figures.py`.
