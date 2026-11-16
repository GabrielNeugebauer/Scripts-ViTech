# Scripts-ViTech

Scripts to run the reference encoders and decoders over the test sequences, and to analyze the results.

| Folder      | Script                                                                      | What it does                                                                                               |
| ----------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `VTM/`      | `run_vtm.py`                                                                | Encodes sequences with the VVC reference encoder (VTM), with the Affine/PROF/BDOF scenarios                |
| `VTM/`      | `run_vtm_decoder.py`                                                        | Decodes the VTM bitstreams and measures the decoding time                                                  |
| `AVM/`      | `run_avm.py`                                                                | Encodes the AOM AV2 CTC v9 sequences with AV2 (AVM) and AV1 (libaom), following the CTC v9                 |
| `Android/`  | `install_decoders.py`                                                       | Installs dav2d and dav1d (and checkasm) on an Android phone over adb and checks them                       |
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

## `AVM/run_avm.py`: AV2 and AV1 encoders (AOM AV2 CTC v9.0)

Encodes the sequences with `avmenc` (AV2) and/or `aomenc` (AV1, standard libaom) using the AOM AV2 CTC v9.0 command lines (CWG-G082o, March 2026), and decodes each stream with the matching reference decoder to record its MD5. Run it from any folder: paths in `config.json` are relative to `AVM/`.

On the first run it creates `config.json` with default values and exits. An older `config.json` gets the missing keys added (the old `extra_args` becomes `extra_args_av2`), and the script exits so you can review the paths.

| Key                                | Meaning                                                                                  |
| ---------------------------------- | ---------------------------------------------------------------------------------------- |
| `avm_binary`, `avmdec_binary`      | AVM encoder and decoder (`avmenc`, `avmdec`)                                              |
| `aomenc_binary`, `aomdec_binary`   | libaom encoder and decoder (`aomenc`, `aomdec`)                                           |
| `cfg_dir`                          | Folder with `av2/` and `av1/` `.cfg` files (default `./cfg`)                             |
| `videos_dir`                       | Folder with the `.y4m` sequences (searched recursively)                                   |
| `bin_output_dir`                   | Where the `.obu` streams are written                                                      |
| `reports_dir`                      | Where the logs, time logs, results CSV and run manifests are written                     |
| `threads`                          | Thread budget for parallel jobs (`0` = `cpu_count − 1`)                                   |
| `extra_args_av2`, `extra_args_av1` | Extra arguments for each encoder. Runs with extra arguments are marked as non-conforming  |

The binaries built by `AV2-Android` (`scripts/build_avm.sh`, `scripts/build_libaom.sh`) are the defaults. Use the AVM commit that `dav2d` decodes (the `av2-normative` pin in `AV2-Android/VERSIONS.md`).

It asks for:

1. The codec: AV2, AV1, or both.
2. The configuration: Random Access (§4.2), Low Delay (§4.3) or All Intra (§4.1).
3. The mode: **CTC** (tiles per class) or **Verification** (§4.9: one tile and one thread for every class, 30 frames in All Intra).
4. The videos. Each one shows its CTC v9 class.
5. The QPs (Table 12). Blank selects all six: 110–235 for RA/LD, 85–210 for AI.
6. The number of frames. Blank uses the CTC value (130 for RA/LD, 15 for AI). Any other value marks the runs as non-conforming.

What it applies from the CTC v9:

- **Command lines:** `cfg/av2/<config>.cfg` holds the CTC line without `--qp` and `--limit`, which the script adds. `cfg/av1/` holds the same line for libaom. libaom has no `--subgop-config-str=ld`, so that option is AV2-only.
- **Class options:** `cfg/<codec>/class_<class>.cfg`. AV2: `--bit-depth=10` for A2, A4 and B1; `--enable-intrabc-ext=2` for A4 and A5, `=1` for the others; `--tune-content=screen` for B2. AV1 gets the same `--bit-depth=10` and `--tune-content=screen` (libaom has no `--enable-intrabc-ext`).
- **Class:** taken from `ctc_v9_sequences.json` (the CTC v9 tables, classes A1–A5, B1, B2 and E), by file name. A video that isn't in the tables uses its folder name as the class and is marked `ctc_v9 = nao`.
- **Tiles:** RA: 4 tiles for A1/E, 2 tiles for A2/B1. LD: 8 tiles for A2/B1, 2 tiles for A3. Two tiles for other 4K videos. One tile and one thread otherwise. AV1 uses the same tiles as AV2.
- **Sources:** checks the y4m header and frame count, and compares each source's MD5 with the value published in the CTC (cached in `md5_fontes.json`). It asks before continuing if anything differs.
- **Time:** each encode and decode runs under `/usr/bin/time --verbose` (§5, method 1). Install it with `sudo apt install time` if it is missing.
- **Bitrate:** `round(bytes × 8 × fps_num / fps_den / frames / 1000, 6)` (§4).

**AV1 QPs:** `aomenc` takes `--cq-level` (0–63), not a qindex. The script uses the cq-level whose qindex is closest to the CTC qindex (110→28, 135→34, 160→40, 185→46, 210→53, 235→59). Standard libaom and AVM have different quantizer step tables, so the same qindex doesn't give the same quality: AV1 comes out at a much higher bitrate at the high QPs. The CTC's own AV1 anchor (`research-alt-v1-anchor_r4.0`) extends the quantizer range, but its streams aren't standard AV1 and dav1d can't decode them.

Jobs run in parallel. Each job reserves as many threads as its tiling uses, up to `threads` in total, largest jobs first. A job whose stream and time logs already exist with exit status 0 is skipped, so a run can be restarted after Ctrl+C. 4K jobs use several GB of RAM each, so lower `threads` if memory runs out.

Outputs, with `<run>` = the configuration name (plus `_verificacao` in verification mode):

```
<bin_output_dir>/<codec>/<run>/<class>/<video>_QP<qp>.obu
<reports_dir>/<codec>/<run>/<class>/<video>_QP<qp>.log            encoder output, with the command line
<reports_dir>/<codec>/<run>/<class>/<video>_QP<qp>_enc_time.txt   /usr/bin/time of the encoder
<reports_dir>/<codec>/<run>/<class>/<video>_QP<qp>_dec_time.txt   /usr/bin/time of the reference decoder
<reports_dir>/resultados_ctc_v9.csv     one row per encode: bitrate, times, max RSS, decoded MD5, conformance, command
<reports_dir>/execucao_<date>.json      run manifest: encoder paths, versions, SHA-256, cfg, selections
```

The decoded MD5 is the reference to check `dav2d`/`dav1d` output against on the phones.

## `Android/install_decoders.py`: dav2d and dav1d on the phone

Pushes the decoders built in `AV2-Android` to an Android phone over adb, in the same layout as `AV2-Android/scripts/install_phone.sh`, so the AV2-Android scripts (`phone_smoke_test.sh`, `bench.py`) use what it installs. Build the decoders first with `AV2-Android/scripts/build_dav2d.sh` and `build_dav1d.sh`.

On the first run it creates `config.json` with default values and exits.

| Key               | Meaning                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `adb_binary`      | `adb` command or path (default `adb`)                                   |
| `av2_android_dir` | The AV2-Android folder, which has `build/` and `src/` (default `../../AV2-Android`) |
| `remote_dir`      | Folder on the phone for the executables (default `/data/local/tmp/av2`) |
| `shared_dir`      | Folder in the phone's Downloads for the files to open (default `/sdcard/Download/av2`) |

It asks for:

1. The phone, from `adb devices` (shows the model, Android version, SoC and ABIs).
2. The architecture. The default comes from the phone's ABI list (`arm64-v8a` → `arm64`, otherwise `armv7`).
3. The decoders: `dav2d`, `dav1d` or both. Each one shows its source commit, or the build command if it isn't built.
4. Whether to install checkasm, run it afterwards, and decode the `dav2d-test-data` conformance streams on the phone to check their MD5s.

Each pushed file is made executable and its SHA-256 on the phone is compared with the local file. `VERSIONS` gets one line per decoder (name, source commit, arch, install date); lines of decoders not installed in this run are kept.

The executables can't go to Downloads: Android mounts the shared storage (`/sdcard`) with `noexec`, so a binary there fails with "Permission denied". They stay in `remote_dir`, and the files you open on the phone go to `shared_dir`:

```
<remote_dir>/dav2d, dav1d                   decoders
<remote_dir>/checkasm, checkasm-dav1d       checkasm of dav2d and dav1d
<remote_dir>/VERSIONS                       read by the AV2-Android scripts
<shared_dir>/VERSIONS.txt                   copy of VERSIONS
<shared_dir>/streams/                       dav2d-test-data streams (if checked)
<shared_dir>/instalacao_<date>.txt          versions, stream results and checkasm result of this run
```

## `Analysis/`

Computes BD-Rate, BD-PSNR and the encoding/decoding time ratios (EncT/DecT) from `data/relatorio_final.csv` and `data/tempos_decodificacao.csv`, and makes the article's tables and figures. Setup, options and outputs are in [`Analysis/README.md`](Analysis/README.md).

```bash
cd Analysis
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python bd_metrics.py && python summary_stats.py && python make_figures.py && python decode_metrics.py
```
