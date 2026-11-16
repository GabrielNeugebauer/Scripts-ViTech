#!/usr/bin/env python3
"""Encodes the AOM AV2 CTC v9.0 sequences with AVM (AV2) and libaom (AV1), with the same settings for both.

Interactive (prompts in Portuguese). Paths come from config.json, next to this script.
See the AVM section of ../README.md.
"""
import concurrent.futures
import csv
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "config.json"
SEQUENCES_FILE = "ctc_v9_sequences.json"
TIME_BIN = "/usr/bin/time"

DEFAULT_CONFIG = {
    "avm_binary": "../../AV2-Android/build/avm-x86/avmenc",
    "avmdec_binary": "../../AV2-Android/build/avm-x86/avmdec",
    "aomenc_binary": "../../AV2-Android/build/libaom-x86/aomenc",
    "aomdec_binary": "../../AV2-Android/build/libaom-x86/aomdec",
    "cfg_dir": "./cfg",
    "videos_dir": "../../AVM/videos_referencia",
    "bin_output_dir": "../../AVM/bin_outputs",
    "reports_dir": "../../AVM/relatorios_execucao",
    "threads": 0,
    "extra_args_av2": "",
    "extra_args_av1": "",
}

# CTC v9 Table 12 (qindex) and frame counts (sections 4.1-4.3; 4.9 for the verification mode).
CTC_QPS = {
    "random_access": [110, 135, 160, 185, 210, 235],
    "low_delay": [110, 135, 160, 185, 210, 235],
    "all_intra": [85, 110, 135, 160, 185, 210],
}
CTC_FRAMES = {"random_access": 130, "low_delay": 130, "all_intra": 15}
VERIFICATION_AI_FRAMES = 30
CONFIG_LABELS = {"random_access": "Random Access (RA, §4.2)", "low_delay": "Low Delay (LD, §4.3)",
                 "all_intra": "All Intra (AI, §4.1)"}

# libaom quantizer_to_qindex (av1/encoder/av1_quantize.c): aomenc takes --cq-level 0..63, not a qindex.
AV1_QINDEX = [q * 4 for q in range(62)] + [249, 255]


def av1_cq_level(qindex):
    """cq-level whose qindex is closest to the CTC qindex (ties go to the higher cq-level)."""
    return min(range(64), key=lambda q: (abs(AV1_QINDEX[q] - qindex), -q))


CODECS = {
    "av2": {"label": "AV2 (avmenc)", "enc": "avm_binary", "dec": "avmdec_binary"},
    "av1": {"label": "AV1 (aomenc)", "enc": "aomenc_binary", "dec": "aomdec_binary"},
}

SINGLE_TILE = ["--tile-rows=0", "--tile-columns=0", "--threads=1"]
TWO_TILES = ["--row-mt=0", "--threads=2", "--tile-rows=0", "--tile-columns=1"]
FOUR_TILES = ["--row-mt=0", "--threads=4", "--tile-rows=0", "--tile-columns=2"]
EIGHT_TILES = ["--row-mt=0", "--threads=8", "--tile-rows=1", "--tile-columns=2"]


def tiling(config_name, cls, width, height, verification):
    """Tile options of CTC v9 sections 4, 4.2 and 4.3 (4.9 in verification mode). Returns (args, threads)."""
    if verification:
        return SINGLE_TILE, 1
    if config_name == "random_access":
        if cls in ("A1", "E", "G1"):
            return FOUR_TILES, 4
        if cls in ("A2", "B1"):
            return TWO_TILES, 2
    elif config_name == "low_delay":
        if cls in ("A2", "B1"):
            return EIGHT_TILES, 8
        if cls == "A3":
            return TWO_TILES, 2
    if width >= 3840 and height >= 2160:
        return TWO_TILES, 2
    return SINGLE_TILE, 1


def parse_selection(selection_str, max_val):
    """Parses a string like '1,2,3-5' into a sorted list of unique integers."""
    selected = set()
    for part in selection_str.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                start, end = map(int, part.split('-'))
                selected.update(i for i in range(start, end + 1) if 1 <= i <= max_val)
            elif 1 <= int(part) <= max_val:
                selected.add(int(part))
            else:
                print(f"Aviso: Valor fora do limite ignorado '{part}'")
        except ValueError:
            print(f"Aviso: Entrada inválida ignorada '{part}'")
    return sorted(selected)


def menu(title, options, prompt, multi=False, default_all=False):
    """Numbered menu. Returns a 0-based index, or a list of them when multi=True."""
    print("\n========================================")
    print(f"  {title}")
    print("========================================")
    for idx, opt in enumerate(options, 1):
        print(f"[{idx}] {opt}")
    print("========================================")
    while True:
        answer = input(prompt).strip()
        if not answer and default_all:
            return list(range(len(options)))
        if multi:
            sel = parse_selection(answer, len(options))
            if sel:
                return [i - 1 for i in sel]
        elif answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("Seleção inválida.")


def ask_yes(prompt):
    return input(prompt).strip().lower() in ("s", "sim", "y", "yes")


def read_args(path):
    """Arguments of a .cfg file; text after '#' is a comment."""
    with open(path) as f:
        return [a for line in f for a in line.split('#', 1)[0].split()]


def y4m_info(path):
    """Width, height, fps, bit depth and frame count of a 4:2:0 y4m file."""
    with open(path, 'rb') as f:
        raw = f.readline()
    header = raw.decode('ascii', 'replace').split()
    if not header or header[0] != "YUV4MPEG2":
        raise ValueError("não é um arquivo y4m")
    info = {"chroma": "420jpeg", "fps_num": 0, "fps_den": 1}
    for tok in header[1:]:
        key, val = tok[0], tok[1:]
        if key == 'W':
            info["width"] = int(val)
        elif key == 'H':
            info["height"] = int(val)
        elif key == 'F':
            num, den = val.split(':')
            info["fps_num"], info["fps_den"] = int(num), int(den)
        elif key == 'C':
            info["chroma"] = val
    if not info["chroma"].startswith("420"):
        raise ValueError(f"amostragem {info['chroma']} não suportada (a CTC usa 4:2:0)")
    if not info["fps_num"]:
        raise ValueError("cabeçalho sem taxa de quadros (F)")
    m = re.search(r'p(\d+)$', info["chroma"])
    info["bit_depth"] = int(m.group(1)) if m else 8
    frame_bytes = info["width"] * info["height"] * 3 // 2 * (2 if info["bit_depth"] > 8 else 1)
    info["frames"] = (os.path.getsize(path) - len(raw)) // (len(b"FRAME\n") + frame_bytes)
    return info


def file_hash(path, algo):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def cached_md5(path, cache):
    """MD5 of a source, cached by path, size and mtime (hashing a 4K source takes seconds)."""
    st = os.stat(path)
    key = os.path.abspath(path)
    entry = cache.get(key)
    if not entry or entry["size"] != st.st_size or entry["mtime"] != st.st_mtime:
        entry = cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "md5": file_hash(path, "md5")}
    return entry["md5"]


def encoder_version(binary):
    out = subprocess.run([binary, "--help"], capture_output=True, text=True).stdout
    m = re.search(r'AOMedia Project \S+ Encoder (\S+)', out)
    return m.group(1) if m else "?"


def parse_time_log(path):
    """User/system/wall seconds, max RSS and exit status from a /usr/bin/time --verbose log."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return {}
    out = {}
    for key, pattern in (("user_s", r'User time \(seconds\): ([\d.]+)'),
                         ("sys_s", r'System time \(seconds\): ([\d.]+)'),
                         ("max_rss_kb", r'Maximum resident set size \(kbytes\): (\d+)'),
                         ("exit", r'Exit status: (\d+)')):
        m = re.search(pattern, text)
        if m:
            out[key] = m.group(1)
    m = re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)', text)
    if m:
        secs = 0.0
        for part in m.group(1).split(':'):
            secs = secs * 60 + float(part)
        out["wall_s"] = f"{secs:.2f}"
    return out


class Slots:
    """Thread budget: a job holds as many slots as its encoder threads (1, 2, 4 or 8 by the CTC tiling)."""

    def __init__(self, total):
        self.total = total
        self.free = total
        self.cv = threading.Condition()

    def acquire(self, n):
        n = min(n, self.total)
        with self.cv:
            self.cv.wait_for(lambda: self.free >= n)
            self.free -= n
        return n

    def release(self, n):
        with self.cv:
            self.free += n
            self.cv.notify_all()


CSV_FIELDS = ["data", "codec", "encoder_version", "configuracao", "modo", "classe", "sequencia", "ctc_v9",
              "md5_fonte_ok", "largura", "altura", "fps", "bit_depth_fonte", "frames", "qp", "av1_cq_level",
              "av1_qindex", "tiles", "threads", "bytes", "bitrate_kbps", "enc_user_s", "enc_sys_s",
              "enc_wall_s", "enc_max_rss_kb", "dec_user_s", "md5_decodificado", "conforme_ctc", "stream",
              "comando"]


def load_config():
    """config.json merged with the defaults. Returns None when the user has to edit it first."""
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        print(f"[{CONFIG_FILE}] criado com valores padrão.")
        print("Edite-o com os caminhos corretos e execute o script novamente.")
        return None
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    except json.JSONDecodeError:
        print(f"Erro: O arquivo {CONFIG_FILE} possui formato JSON inválido.")
        return None
    missing = [k for k in DEFAULT_CONFIG if k not in config]
    if missing:
        if "extra_args" in config:
            config.setdefault("extra_args_av2", config.pop("extra_args"))
        for k in missing:
            config.setdefault(k, DEFAULT_CONFIG[k])
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"[{CONFIG_FILE}] não tinha {', '.join(missing)}; as chaves foram adicionadas com valores padrão.")
        print("Revise os caminhos e execute o script novamente.")
        return None
    return config


def main():
    os.chdir(HERE)
    config = load_config()
    if config is None:
        return
    if not os.path.exists(TIME_BIN):
        print(f"Erro: {TIME_BIN} não encontrado (a CTC mede o tempo com ele). Instale com: sudo apt install time")
        return
    with open(SEQUENCES_FILE) as f:
        ctc_sequences = json.load(f)
    cfg_dir, videos_dir = config["cfg_dir"], config["videos_dir"]
    bin_dir, reports_dir = config["bin_output_dir"], config["reports_dir"]

    # 1. CODEC
    codecs = [["av2"], ["av1"], ["av2", "av1"]][
        menu("CODEC", ["AV2 (avmenc)", "AV1 (aomenc)", "AV2 e AV1"], "Selecione o codec: ")]
    for codec in codecs:
        for key in (CODECS[codec]["enc"], CODECS[codec]["dec"]):
            if not os.path.isfile(config[key]):
                print(f"Erro: Binário não encontrado ({key}): {config[key]}")
                print("Verifique o caminho no config.json.")
                return

    # 2. CONFIGURAÇÃO
    config_names = [n for n in CTC_QPS
                    if all(os.path.isfile(os.path.join(cfg_dir, c, f"{n}.cfg")) for c in codecs)]
    if not config_names:
        print(f"Nenhuma configuração encontrada em {cfg_dir}/<codec>/.")
        return
    config_name = config_names[menu("CONFIGURAÇÃO (CTC v9)", [CONFIG_LABELS[n] for n in config_names],
                                    "Selecione a configuração: ")]

    # 3. MODO
    verification = menu("MODO", [
        "CTC (tiles por classe, §4.1-4.3)",
        "Verificação (§4.9: 1 tile e 1 thread em todas as classes; AI com 30 frames)",
    ], "Selecione o modo: ") == 1
    mode = "verificacao" if verification else "ctc"

    # 4. VÍDEOS
    videos = []
    for root, _, files in os.walk(videos_dir):
        for name in files:
            if name.lower().endswith(".y4m"):
                path = os.path.join(root, name)
                stem = os.path.splitext(name)[0]
                entry = ctc_sequences.get(stem)
                folder = os.path.basename(root)
                videos.append({"name": stem, "path": path, "rel": os.path.relpath(path, videos_dir),
                               "ctc": entry, "cls": entry["class"] if entry else folder, "folder": folder})
    if not videos:
        print(f"Nenhum vídeo .y4m encontrado na pasta: {videos_dir}")
        return
    videos.sort(key=lambda v: (v["cls"], v["name"]))
    rows = [f"{v['cls']:<3} {v['rel']}" + ("" if v["ctc"] else "   (fora da CTC v9)") for v in videos]
    chosen = [videos[i] for i in menu("VÍDEOS", rows, "Selecione os vídeos (ex: 1,2,3 ou 1-3,5): ", multi=True)]

    # 5. QP
    qps = CTC_QPS[config_name]
    qp_rows = [f"QP {qp}" + (f"   (AV1: --cq-level={av1_cq_level(qp)}, qindex {AV1_QINDEX[av1_cq_level(qp)]})"
                             if "av1" in codecs else "") for qp in qps]
    selected_qps = [qps[i] for i in menu(f"QP (CTC v9, Tabela 12, {config_name})", qp_rows,
                                         "Selecione os QPs (em branco = todos): ", multi=True, default_all=True)]

    # 6. FRAMES
    ctc_frames = VERIFICATION_AI_FRAMES if verification and config_name == "all_intra" else CTC_FRAMES[config_name]
    print("\n========================================")
    print("      QUANTIDADE DE FRAMES (--limit)    ")
    print("========================================")
    answer = input(f"Frames a codificar (em branco = {ctc_frames}, valor da CTC): ").strip()
    frames = int(answer) if answer.isdigit() and int(answer) > 0 else ctc_frames
    if frames != ctc_frames:
        print(f"Aviso: {frames} frames não seguem a CTC v9; o relatório marca essas execuções como não conformes.")

    # 7. CONFERÊNCIA DAS FONTES
    print("\nConferindo as fontes (cabeçalho y4m e MD5 publicado na CTC v9)...")
    os.makedirs(reports_dir, exist_ok=True)
    cache_path = os.path.join(reports_dir, "md5_fontes.json")
    try:
        with open(cache_path) as f:
            md5_cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        md5_cache = {}
    problems = []
    for v in chosen:
        try:
            v["info"] = y4m_info(v["path"])
        except (OSError, ValueError) as e:
            print(f"Erro em {v['rel']}: {e}")
            return
        if v["info"]["frames"] < frames:
            problems.append(f"{v['name']}: tem {v['info']['frames']} frames, precisa de {frames}")
        v["md5_ok"] = None
        if not v["ctc"]:
            problems.append(f"{v['name']}: não está nas tabelas da CTC v9; usando a classe da pasta ({v['cls']})")
            continue
        if v["folder"] != v["cls"]:
            print(f"Aviso: {v['name']} está na pasta {v['folder']}, mas é da classe {v['cls']} na CTC v9.")
        v["md5_ok"] = cached_md5(v["path"], md5_cache) == v["ctc"]["md5"]
        if not v["md5_ok"]:
            problems.append(f"{v['name']}: MD5 diferente do publicado na CTC v9")
    with open(cache_path, 'w') as f:
        json.dump(md5_cache, f, indent=1)
    for p in problems:
        print(f"  - {p}")
    if problems and not ask_yes("Há problemas acima. Continuar mesmo assim? [s/N]: "):
        return

    # 8. TAREFAS
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    versions = {c: encoder_version(config[CODECS[c]["enc"]]) for c in codecs}
    run_dir = config_name if mode == "ctc" else f"{config_name}_{mode}"
    jobs = []
    for codec in codecs:
        base_args = read_args(os.path.join(cfg_dir, codec, f"{config_name}.cfg"))
        extra = config[f"extra_args_{codec}"].split()
        for v in chosen:
            info = v["info"]
            class_cfg = os.path.join(cfg_dir, codec, f"class_{v['cls']}.cfg")
            if os.path.isfile(class_cfg):
                class_args = read_args(class_cfg)
            else:
                class_args = []
                print(f"Aviso: {class_cfg} não existe; {v['name']} vai sem opções de classe.")
            tile_args, threads = tiling(config_name, v["cls"], info["width"], info["height"], verification)
            out_dir = os.path.join(bin_dir, codec, run_dir, v["cls"])
            log_dir = os.path.join(reports_dir, codec, run_dir, v["cls"])
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(log_dir, exist_ok=True)
            for qp in selected_qps:
                qp_args = [f"--qp={qp}"] if codec == "av2" else [f"--cq-level={av1_cq_level(qp)}"]
                base = f"{v['name']}_QP{qp}"
                stream = os.path.join(out_dir, base + ".obu")
                jobs.append({
                    "codec": codec, "video": v, "qp": qp, "threads": threads, "stream": stream,
                    "log": os.path.join(log_dir, base + ".log"),
                    "enc_time": os.path.join(log_dir, base + "_enc_time.txt"),
                    "dec_time": os.path.join(log_dir, base + "_dec_time.txt"),
                    "enc_cmd": ([config[CODECS[codec]["enc"]]] + base_args + class_args + tile_args
                                + [f"--limit={frames}"] + qp_args + extra + ["-o", stream, v["path"]]),
                    "tiles": " ".join(tile_args),
                    "conforme": frames == ctc_frames and not extra and v["md5_ok"] is True,
                    "work": info["width"] * info["height"] * frames,
                })
    # Smallest videos first (pixels x frames), and the highest QP (fastest encode) first within a video, so the
    # first streams are ready early.
    jobs.sort(key=lambda j: (j["work"], -j["qp"], j["codec"]))

    total_slots = config["threads"] or max(1, (os.cpu_count() or 2) - 1)
    print("\n========================================")
    print(f" {len(jobs)} execuções: " + ", ".join(f"{CODECS[c]['label']} {versions[c]}" for c in codecs))
    print(f" {config_name}, modo {mode}, {frames} frames, até {total_slots} threads ao mesmo tempo")
    print("========================================")
    print("Exemplo de comando:\n  " + " ".join(jobs[0]["enc_cmd"]) + "\n")
    if not ask_yes("Iniciar? [s/N]: "):
        return

    manifest = {
        "data": stamp, "ctc": "AOM AV2 CTC v9.0 (CWG-G082o)", "configuracao": config_name, "modo": mode,
        "frames": frames, "qps": selected_qps, "cpu": platform.processor() or platform.machine(),
        "threads": total_slots, "sequencias": [v["name"] for v in chosen],
        "codecs": {c: {"encoder": os.path.abspath(config[CODECS[c]["enc"]]), "versao": versions[c],
                       "encoder_sha256": file_hash(config[CODECS[c]["enc"]], "sha256"),
                       "decoder": os.path.abspath(config[CODECS[c]["dec"]]),
                       "cfg": read_args(os.path.join(cfg_dir, c, f"{config_name}.cfg")),
                       "extra_args": config[f"extra_args_{c}"]} for c in codecs},
    }
    with open(os.path.join(reports_dir, f"execucao_{stamp}.json"), 'w') as f:
        json.dump(manifest, f, indent=1)

    csv_path = os.path.join(reports_dir, "resultados_ctc_v9.csv")
    state = {"done": 0.0, "write_header": not os.path.exists(csv_path)}
    total_work = sum(j["work"] for j in jobs)
    lock = threading.Lock()
    slots = Slots(total_slots)

    def update_bar():
        percent = 100 * state["done"] / total_work
        filled = int(40 * percent // 100)
        sys.stdout.write(f"\r\033[K[ Progresso Global: |{'█' * filled}{'-' * (40 - filled)}| {percent:.1f}% ]")
        sys.stdout.flush()

    def print_msg(msg):
        with lock:
            sys.stdout.write("\r\033[K" + msg + "\n")
            update_bar()

    def add_progress(amount):
        with lock:
            state["done"] += amount
            update_bar()

    def encode_and_decode(job, task_id):
        """Runs the encoder and the reference decoder. Returns the decoded MD5, or None on error."""
        codec = job["codec"]
        per_frame = job["work"] / frames
        counted = 0
        try:
            with open(job["log"], "w") as log:
                log.write(" ".join(job["enc_cmd"]) + "\n\n")
                proc = subprocess.Popen([TIME_BIN, "--verbose", f"--output={job['enc_time']}"] + job["enc_cmd"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        errors="replace")
                for line in proc.stdout:  # text mode splits the encoders' \r progress lines too
                    log.write(line)
                    if codec == "av2":
                        done = counted + 1 if line.startswith("POC:") else counted
                    else:
                        m = re.search(r'frame\s+\d+/(\d+)', line)
                        done = int(m.group(1)) if m else counted
                    done = min(done, frames)
                    if done > counted:
                        add_progress((done - counted) * per_frame)
                        counted = done
                proc.wait()
        finally:
            add_progress((frames - counted) * per_frame)
        if proc.returncode != 0:
            print_msg(f"[ ERRO ] {task_id}: o encoder saiu com código {proc.returncode}; veja {job['log']}")
            return None
        dec = subprocess.run([TIME_BIN, "--verbose", f"--output={job['dec_time']}",
                              config[CODECS[codec]["dec"]], "--rawvideo", "--md5", job["stream"]],
                             capture_output=True, text=True)
        if dec.returncode != 0 or not dec.stdout.split():
            print_msg(f"[ ERRO ] {task_id}: o decodificador falhou: {dec.stderr.strip()[-300:]}")
            return None
        return dec.stdout.split()[0]

    def run_job(job):
        v, codec, qp = job["video"], job["codec"], job["qp"]
        task_id = f"{codec} {v['name'][:28]} QP{qp}"
        if (os.path.exists(job["stream"]) and parse_time_log(job["enc_time"]).get("exit") == "0"
                and parse_time_log(job["dec_time"]).get("exit") == "0"):
            add_progress(job["work"])
            print_msg(f"[ Já feito ] {task_id}")
            return
        held = slots.acquire(job["threads"])
        try:
            print_msg(f"[ Iniciando ] {task_id} ({held} thread(s))")
            decoded_md5 = encode_and_decode(job, task_id)
        except Exception as e:
            print_msg(f"[ ERRO ] {task_id}: {e}")
            return
        finally:
            slots.release(held)
        if decoded_md5 is None:
            return

        info = v["info"]
        size = os.path.getsize(job["stream"])
        bitrate = round(size * 8 * info["fps_num"] / info["fps_den"] / frames / 1000, 6)
        enc_t, dec_t = parse_time_log(job["enc_time"]), parse_time_log(job["dec_time"])
        cq = av1_cq_level(qp) if codec == "av1" else None
        row = {
            "data": stamp, "codec": codec, "encoder_version": versions[codec], "configuracao": config_name,
            "modo": mode, "classe": v["cls"], "sequencia": v["name"], "ctc_v9": "sim" if v["ctc"] else "nao",
            "md5_fonte_ok": {True: "sim", False: "nao"}.get(v["md5_ok"], ""), "largura": info["width"],
            "altura": info["height"], "fps": f"{info['fps_num']}/{info['fps_den']}",
            "bit_depth_fonte": info["bit_depth"], "frames": frames, "qp": qp,
            "av1_cq_level": "" if cq is None else cq, "av1_qindex": "" if cq is None else AV1_QINDEX[cq],
            "tiles": job["tiles"], "threads": job["threads"], "bytes": size, "bitrate_kbps": f"{bitrate:.6f}",
            "enc_user_s": enc_t.get("user_s", ""), "enc_sys_s": enc_t.get("sys_s", ""),
            "enc_wall_s": enc_t.get("wall_s", ""), "enc_max_rss_kb": enc_t.get("max_rss_kb", ""),
            "dec_user_s": dec_t.get("user_s", ""), "md5_decodificado": decoded_md5,
            "conforme_ctc": "sim" if job["conforme"] else "nao", "stream": os.path.abspath(job["stream"]),
            "comando": " ".join(job["enc_cmd"]),
        }
        with lock:
            with open(csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                if state["write_header"]:
                    writer.writeheader()
                    state["write_header"] = False
                writer.writerow(row)
        print_msg(f"[ Concluído ] {task_id}: {bitrate:.2f} kbps, encoder {row['enc_user_s']} s (user)")

    update_bar()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(jobs), total_slots)) as executor:
        list(executor.map(run_job, jobs))
    sys.stdout.write("\n")
    print("========================================")
    print("    Todas as execuções finalizadas!     ")
    print(f"    Resultados: {os.path.abspath(csv_path)}")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecução cancelada pelo usuário.")
        sys.exit(1)
