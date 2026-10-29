# Scripts-ViTech

Scripts to run the reference encoders and decoders over the test sequences, and to analyze the results.

| Folder      | Script                                                                      | What it does                                                                                               |
| ----------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `VTM/`      | `run_vtm.py`                                                                | Encodes sequences with the VVC reference encoder (VTM), with the Affine/PROF/BDOF scenarios                |
| `VTM/`      | `run_vtm_decoder.py`                                                        | Decodes the VTM bitstreams and measures the decoding time                                                  |
| `AVM/`      | `run_avm.py`                                                                | Encodes sequences with the AV2 reference encoder (AVM), following the AOM CTC                              |
| `Analysis/` | `bd_metrics.py`, `summary_stats.py`, `make_figures.py`, `decode_metrics.py` | BD-Rate, BD-PSNR, EncT/DecT, summary tables and figures. See [`Analysis/README.md`](Analysis/README.md) |

```
run_vtm.py          → .bin bitstreams + encoder logs ──→ (compiled from the logs) Analysis/data/relatorio_final.csv
run_vtm_decoder.py  → decoder logs + tempos_decodificacao.csv ──→ (copied to) Analysis/data/
```

`Videos.txt` holds a list of sequence numbers (`100,101,131,2,3,122,127`). No script reads it.

## Common behavior of the runners

`run_vtm.py`, `run_vtm_decoder.py` and `run_avm.py` work the same way:

- **Interactive:** they ask the questions in the terminal (in Portuguese), as numbered menus. Selections accept lists and ranges, such as `1,2,3` or `1-3,5`.
- **Config:** the paths come from a `config.json` in the script's folder. Run each script from its own folder (`cd VTM` or `cd AVM`), since the paths are relative to it. `config.json` is git-ignored because the paths differ on each machine.
- **Parallel:** encodings run in parallel. The encoders use up to `cpu_count − 1` threads, and the decoder asks how many to use.
- **Logs:** each execution writes a full log. The terminal shows a global progress bar and a summary when each task finishes.
- **Ctrl+C** cancels the run.

> Parallel runs compete for the CPU and change the measured times. For timing results, run fewer jobs at once, or a single one.

## `VTM/run_vtm.py`: VVC encoder

On the first run it creates `config.json` with default values and exits; edit it and run again.

| Key                | Meaning                                                                                                        |
| ------------------ | -------------------------------------------------------------------------------------------------------------- |
| `vtm_binary`       | VTM encoder binary (`EncoderAppStatic`; a name ending in `d` is usually the debug build, which is much slower) |
| `cfg_dir`          | Folder with the main configurations (`encoder_randomaccess_vtm.cfg`, …)                                        |
| `per_sequence_dir` | Folder with the per-sequence `.cfg` files                                                                      |
| `videos_dir`       | Folder with the `.yuv` sequences (searched recursively)                                                        |
| `bin_output_dir`   | Where the bitstreams (`.bin`) are written                                                                      |
| `reports_dir`      | Where the encoder logs (`.log`) are written                                                                    |
| `extra_args`       | Extra arguments added to every command                                                                         |

It asks for:

1. The main configuration file.
2. The videos.
3. The per-sequence configuration file for each video. It suggests the one whose name starts with the video's name; press Enter to accept.
4. The QPs (22, 27, 32, 37).
5. The number of frames. Blank encodes all frames.
6. The scenarios:

| #   | Scenario        | VTM arguments                 | Output suffix     | Article |
| --- | --------------- | ----------------------------- | ----------------- | ------- |
| 1   | Default         | none                          | (none)            | —       |
| 2   | All_OFF         | `--Affine=0 --PROF=0 --BIO=0` | `_All_OFF`        | C5      |
| 3   | BIO_ON          | `--Affine=0 --PROF=0 --BIO=1` | `_BIO_ON`         | C2      |
| 4   | Affine_ON       | `--Affine=1 --PROF=0 --BIO=0` | `_Affine_ON`      | C4      |
| 5   | Affine_PROF_ON  | `--Affine=1 --PROF=1 --BIO=0` | `_Affine_PROF_ON` | C3      |
| 6   | Affine_BIO_ON   | `--Affine=1 --PROF=0 --BIO=1` | `_Affine_BIO_ON`  | C1      |
| 7   | All_ON (anchor) | `--Affine=1 --PROF=1 --BIO=1` | `_All_ON`         | C0      |

Width, height and frame rate are read from the file name (`Name_WxH_FPS.yuv`). The outputs are `<video>_QP<qp><suffix>.bin` and `<video>_QP<qp><suffix>.log`.

## `VTM/run_vtm_decoder.py`: VVC decoder

Uses the same `config.json` as `run_vtm.py`, so run `run_vtm.py` once first. These optional keys can be added:

| Key                   | Default                                       | Meaning                                                  |
| --------------------- | --------------------------------------------- | -------------------------------------------------------- |
| `vtm_decoder_binary`  | `vtm_binary` with `EncoderApp` → `DecoderApp` | VTM decoder binary                                       |
| `decoder_reports_dir` | `../../VTM/relatorios_decodificacao`          | Where the decoder logs and the CSV are written           |
| `decoded_output_dir`  | `../../VTM/videos_decodificados`              | Where the decoded `.yuv` files are written, if requested |
| `decoder_extra_args`  | (empty)                                       | Extra arguments for the decoder                          |

It reads the bitstreams from `bin_output_dir`, grouped by video, and asks for:

1. The bitstreams to decode. Blank decodes all of them.
2. How many times to decode each one. Use 3 or more for timing.
3. How many decodings to run in parallel. Use 1 for clean timings.
4. Whether to save the decoded video. Writing the `.yuv` adds to the measured time, and only the first run writes it.

Each decoding writes `<bitstream>_dec[_runN].log` and appends a row to `tempos_decodificacao.csv` as soon as it finishes. Earlier sessions are kept, and each row has a `Date` column.

| Column              | Meaning                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `Scenario`          | `C0`–`C5`, from the bitstream suffix (`Padrão` for the default scenario) |
| `Video`, `QP`       | From the bitstream name                                                  |
| `Run`               | Repetition number                                                        |
| `Decoding time`     | `Total Time` printed by the VTM decoder (s)                              |
| `Wall time`         | Time measured by the script, including process start-up (s)              |
| `Frames`            | Decoded pictures (`POC` lines in the log)                                |
| `Status`            | `Sucesso`, or `Erro: código de saída N (ver <log>)`                      |
| `Bitstream`, `Date` | Bitstream file and the time the decoding finished                        |

A failed decoding doesn't stop the others. To analyze the results, copy the CSV to `Analysis/data/` and run `python decode_metrics.py`.

## `AVM/run_avm.py`: AV2 encoder

On the first run it creates `config.json` with default values and exits.

| Key              | Meaning                                                                             |
| ---------------- | ----------------------------------------------------------------------------------- |
| `avm_binary`     | AVM encoder binary (`avmenc`)                                                       |
| `cfg_dir`        | Folder with the `.cfg` files (default `./cfg`)                                      |
| `videos_dir`     | Folder with the `.yuv`/`.y4m` sequences, in one subfolder per class (`A1`, `B2`, …) |
| `bin_output_dir` | Where the bitstreams (`.obu`) are written                                           |
| `reports_dir`    | Where the encoder logs are written                                                  |
| `extra_args`     | Extra arguments added to every command                                              |

It asks for:

1. The configuration: `all_intra.cfg`, `low_delay.cfg` or `random_access.cfg` from `AVM/cfg/`.
2. The videos.
3. The QPs (85, 110, 135, 160, 185, 210, 235, from the AOM CTC v8.0).
4. The number of frames (`--limit`). Blank uses the value from the cfg.

Each video's subfolder name selects the class configuration `cfg/class_<subfolder>.cfg`, which is added to the command. The outputs are `<video>_QP<qp>.obu` and `<video>_QP<qp>.log`. `stdbuf` is used so that the progress appears in real time.

## `Analysis/`

Computes BD-Rate, BD-PSNR and the encoding/decoding time ratios (EncT/DecT) from `data/relatorio_final.csv` and `data/tempos_decodificacao.csv`, and makes the article's tables and figures. Setup, options and outputs are in [`Analysis/README.md`](Analysis/README.md).

```bash
cd Analysis
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python bd_metrics.py && python summary_stats.py && python make_figures.py && python decode_metrics.py
```
