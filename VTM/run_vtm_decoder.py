import os
import csv
import json
import re
import subprocess
import concurrent.futures
import threading
import sys
import time
from datetime import datetime

CONFIG_FILE = "config.json"
CSV_NAME = "tempos_decodificacao.csv"
CSV_FIELDS = ["Scenario", "Video", "QP", "Run", "Decoding time", "Wall time", "Frames", "Status", "Bitstream", "Date"]

# Sufixos gerados pelo run_vtm.py -> cenários usados no artigo (relatorio_final.csv)
SCENARIO_BY_SUFFIX = {
    "_All_ON": "C0",
    "_Affine_BIO_ON": "C1",
    "_BIO_ON": "C2",
    "_Affine_PROF_ON": "C3",
    "_Affine_ON": "C4",
    "_All_OFF": "C5",
    "": "Padrão",
}

BIN_NAME_RE = re.compile(r'^(?P<base>.+)_QP(?P<qp>\d+)(?P<suffix>_.+)?\.bin$', re.IGNORECASE)
TOTAL_TIME_RE = re.compile(r'Total Time:\s*([\d.]+)\s*sec', re.IGNORECASE)


def parse_selection(selection_str, max_val):
    """Parses a string like '1,2,3-5' into a sorted list of unique integers."""
    selected = set()
    parts = selection_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                for i in range(start, end + 1):
                    if 1 <= i <= max_val:
                        selected.add(i)
            except ValueError:
                print(f"Aviso: Intervalo inválido ignorado '{part}'")
        else:
            try:
                val = int(part)
                if 1 <= val <= max_val:
                    selected.add(val)
                else:
                    print(f"Aviso: Valor fora do limite ignorado '{part}'")
            except ValueError:
                print(f"Aviso: Entrada inválida ignorada '{part}'")
    return sorted(list(selected))


def ask_positive_int(prompt, default):
    while True:
        value = input(prompt).strip()
        if not value:
            return default
        try:
            value = int(value)
            if value >= 1:
                return value
        except ValueError:
            pass
        print("Entrada inválida. Digite um número inteiro maior que zero.")


def parse_bin_name(file_name):
    """'CatRobot_3840x2160_60_QP22_All_OFF.bin' -> ('CatRobot', 22, 'C5')."""
    match = BIN_NAME_RE.match(file_name)
    if not match:
        return None, None, ""
    suffix = match.group("suffix") or ""
    video = match.group("base").split('_')[0]
    return video, int(match.group("qp")), SCENARIO_BY_SUFFIX.get(suffix, suffix.lstrip('_'))


def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"Erro: {CONFIG_FILE} não encontrado.")
        print("Execute o run_vtm.py uma vez para criá-lo, ou rode este script na pasta VTM.")
        return

    with open(CONFIG_FILE, 'r') as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError:
            print(f"Erro: O arquivo {CONFIG_FILE} possui formato JSON inválido.")
            return

    # Por padrão usa o DecoderApp da mesma pasta (e mesmo build) do EncoderApp
    vtm_bin = config.get("vtm_binary", "")
    decoder_bin = config.get("vtm_decoder_binary") or vtm_bin.replace("EncoderApp", "DecoderApp")
    bin_dir = config.get("bin_output_dir", "")
    reports_dir = config.get("decoder_reports_dir", "../../VTM/relatorios_decodificacao")
    decoded_dir = config.get("decoded_output_dir", "../../VTM/videos_decodificados")
    extra_args = config.get("decoder_extra_args", "")

    if not os.path.exists(decoder_bin):
        print(f"Erro: Binário do decodificador VTM não encontrado: {decoder_bin}")
        print("Adicione a chave \"vtm_decoder_binary\" no config.json com o caminho correto.")
        return

    print(f"Decodificador: {decoder_bin}")
    if os.path.basename(decoder_bin).endswith("d"):
        print("Aviso: o binário termina em 'd' e provavelmente é um build de debug (mais lento).")

    os.makedirs(reports_dir, exist_ok=True)

    # 1. SELEÇÃO DOS BITSTREAMS
    bin_files = []
    if os.path.exists(bin_dir):
        for root, dirs, files in os.walk(bin_dir):
            for f in files:
                if f.lower().endswith(".bin"):
                    rel_path = os.path.relpath(os.path.join(root, f), bin_dir)
                    bin_files.append(rel_path.replace(os.sep, '/'))
    bin_files.sort()

    if not bin_files:
        print(f"Nenhum bitstream .bin encontrado na pasta: {bin_dir}")
        return

    print("\n========================================")
    print("        SELEÇÃO DOS BITSTREAMS          ")
    print("========================================")
    # Agrupa por vídeo para facilitar a leitura
    tree = {}
    for idx, path in enumerate(bin_files, 1):
        video, _, _ = parse_bin_name(os.path.basename(path))
        tree.setdefault(video or "Outros", {})[path] = idx

    def _print_tree(node, prefix=""):
        items = sorted(node.items())
        for i, (key, value) in enumerate(items):
            is_last = i == (len(items) - 1)
            connector = "└── " if is_last else "├── "
            if isinstance(value, dict):
                print(f"{prefix}{connector}{key}/")
                extension = "    " if is_last else "│   "
                _print_tree(value, prefix + extension)
            else:
                print(f"{prefix}{connector}[{value}] {key}")

    _print_tree(tree)
    print("========================================")

    bin_sel = input("Selecione os bitstreams (ex: 1,2,3 ou 1-3,5, ou deixe em branco para todos): ").strip()
    if not bin_sel:
        selected_bins = bin_files
    else:
        selected_bins = [bin_files[i-1] for i in parse_selection(bin_sel, len(bin_files))]
    if not selected_bins:
        print("Nenhum bitstream selecionado. Saindo...")
        return

    # 2. REPETIÇÕES (para medir o tempo com mais confiabilidade)
    print("\n========================================")
    print("             REPETIÇÕES                 ")
    print("========================================")
    repetitions = ask_positive_int("Quantas vezes decodificar cada bitstream? (Enter = 1, recomendado 3): ", 1)

    # 3. EXECUÇÕES EM PARALELO
    print("\n========================================")
    print("        EXECUÇÕES EM PARALELO           ")
    print("========================================")
    max_threads = max((os.cpu_count() or 2) - 1, 1)
    threads = ask_positive_int(f"Quantas decodificações em paralelo? (Enter = 1, máximo {max_threads}): ", 1)
    threads = min(threads, max_threads)
    if threads > 1:
        print("Aviso: execuções em paralelo competem pela CPU e alteram os tempos medidos.")

    # 4. SALVAR O VÍDEO DECODIFICADO
    print("\n========================================")
    print("        SAÍDA DO VÍDEO (.yuv)           ")
    print("========================================")
    save_yuv = input("Salvar o vídeo decodificado? (s/N, gravar o .yuv também entra no tempo): ").strip().lower() == "s"
    if save_yuv:
        os.makedirs(decoded_dir, exist_ok=True)

    # Monta a lista de tarefas
    tasks = []
    for rel_path in selected_bins:
        bin_path = os.path.join(bin_dir, rel_path)
        base_name_full = os.path.splitext(os.path.basename(rel_path))[0]
        video, qp, scenario = parse_bin_name(os.path.basename(rel_path))

        for run in range(1, repetitions + 1):
            run_tag = f"_run{run}" if repetitions > 1 else ""
            report_out = os.path.join(reports_dir, f"{base_name_full}_dec{run_tag}.log")

            cmd = [decoder_bin, "-b", bin_path]
            # Só a primeira repetição grava o .yuv (as outras gerariam o mesmo arquivo)
            if save_yuv and run == 1:
                cmd.extend(["-o", os.path.join(decoded_dir, f"{base_name_full}_rec.yuv")])
            if extra_args:
                cmd.extend(extra_args.split())

            tasks.append({
                "cmd": cmd, "report_out": report_out, "run": run, "bitstream": rel_path,
                "video": video or base_name_full, "qp": qp if qp is not None else "", "scenario": scenario,
            })

    total_tasks = len(tasks)
    csv_path = os.path.join(reports_dir, CSV_NAME)
    print(f"\n========================================")
    print(f" Total de {total_tasks} decodificações programadas.")
    print(f" Tempos serão salvos em: {csv_path}")
    print(f"========================================\n")

    # Adiciona ao CSV existente, para acumular resultados de várias sessões
    new_csv = not os.path.exists(csv_path)
    csv_file = open(csv_path, "a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
    if new_csv:
        writer.writeheader()
        csv_file.flush()

    completed = 0
    lock = threading.Lock()

    def update_bar():
        percent = (completed / total_tasks) * 100 if total_tasks else 0
        bar_len = 40
        filled = int(bar_len * percent // 100)
        bar = '█' * filled + '-' * (bar_len - filled)
        sys.stdout.write(f"\r\033[K[ Progresso Global: |{bar}| {percent:.1f}% ({completed}/{total_tasks} decodificações) ]")
        sys.stdout.flush()

    def print_msg(msg):
        with lock:
            sys.stdout.write("\r\033[K")
            sys.stdout.write(msg + "\n")
            update_bar()

    update_bar()

    def run_task(task):
        nonlocal completed
        task_id = f"{os.path.basename(task['bitstream'])[:-4]} (run {task['run']})"
        print_msg(f"[ Iniciando ] {task_id}")

        frames = 0
        vtm_time = ""
        start = time.perf_counter()
        try:
            with open(task["report_out"], "w") as f_out:
                process = subprocess.Popen(task["cmd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in process.stdout:
                    f_out.write(line)
                    if line.lstrip().startswith("POC"):
                        frames += 1
                    match = TOTAL_TIME_RE.search(line)
                    if match:
                        vtm_time = float(match.group(1))
                process.wait()
            if process.returncode != 0:
                status = f"Erro: código de saída {process.returncode} (ver {os.path.basename(task['report_out'])})"
            else:
                status = "Sucesso"
        except Exception as e:
            status = f"Erro: {str(e)}"
        wall_time = time.perf_counter() - start

        if status == "Sucesso" and vtm_time == "":
            status = "Sucesso (sem 'Total Time' no log)"

        with lock:
            writer.writerow({
                "Scenario": task["scenario"], "Video": task["video"], "QP": task["qp"], "Run": task["run"],
                "Decoding time": vtm_time, "Wall time": round(wall_time, 3), "Frames": frames,
                "Status": status, "Bitstream": task["bitstream"],
                "Date": datetime.now().isoformat(timespec="seconds"),
            })
            csv_file.flush()  # Salva imediatamente, para não perder resultados se o script parar
            completed += 1

            shown_time = f"{vtm_time:.3f} s" if vtm_time != "" else f"{wall_time:.3f} s (relógio)"
            sys.stdout.write("\r\033[K")
            sys.stdout.write(f"[ Concluído ] {task_id}: {status} | {frames} frames | {shown_time}\n")
            update_bar()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            list(executor.map(run_task, tasks))
    finally:
        csv_file.close()

    print_msg("\n========================================")
    print_msg("  Todas as decodificações finalizadas!  ")
    print_msg(f"  Tempos em: {csv_path}")
    print_msg("========================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecução cancelada pelo usuário.")
        sys.exit(1)
