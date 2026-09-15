import os
import json
import re
import subprocess
import concurrent.futures
import threading
import sys
import time

CONFIG_FILE = "config.json"

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

def main():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "avm_binary": "../AVM/aom_build/aomenc",
            "cfg_dir": "../AVM/cfg",
            "videos_dir": "../AVM/videos_referencia",
            "bin_output_dir": "../AVM/bin_outputs",
            "reports_dir": "../AVM/relatorios_execucao",
            "extra_args": ""
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"[{CONFIG_FILE}] criado com valores padrão.")
        print("Edite-o com os caminhos corretos e execute o script novamente.")
        return

    with open(CONFIG_FILE, 'r') as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError:
            print(f"Erro: O arquivo {CONFIG_FILE} possui formato JSON inválido.")
            return

    avm_bin = config.get("avm_binary", "")
    cfg_dir = config.get("cfg_dir", "")
    videos_dir = config.get("videos_dir", "")
    bin_dir = config.get("bin_output_dir", "")
    reports_dir = config.get("reports_dir", "")
    extra_args = config.get("extra_args", "")

    if not os.path.exists(avm_bin):
        print(f"Erro: Binário do AVM não encontrado: {avm_bin}")
        print("Verifique o caminho no config.json.")
        return

    # Cria pastas de saída caso não existam
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)

    # 1. SELEÇÃO DO CFG PRINCIPAL
    main_cfgs = []
    if os.path.exists(cfg_dir):
        for f in os.listdir(cfg_dir):
            if f.lower().endswith(".cfg") and not f.lower().startswith("class_") and os.path.isfile(os.path.join(cfg_dir, f)):
                main_cfgs.append(f)
    main_cfgs.sort()

    if not main_cfgs:
        print(f"Nenhum arquivo .cfg encontrado em: {cfg_dir}")
        return

    print("========================================")
    print("        SELEÇÃO DA CONFIGURAÇÃO         ")
    print("========================================")
    for idx, cfg in enumerate(main_cfgs, 1):
        print(f"[{idx}] {cfg}")
    print("========================================")
    
    while True:
        try:
            sel = int(input("Selecione o CFG (digite o número): "))
            if 1 <= sel <= len(main_cfgs):
                selected_main_cfg = os.path.join(cfg_dir, main_cfgs[sel-1])
                break
            else:
                print("Número fora da lista.")
        except ValueError:
            print("Entrada inválida. Digite um número.")

    with open(selected_main_cfg, 'r') as f:
        cfg_content = f.read().replace('\n', ' ')
        cfg_args = [arg for arg in cfg_content.split() if arg]

    # 2. SELEÇÃO DE VÍDEOS
    video_files = []
    if os.path.exists(videos_dir):
        for root, _, files in os.walk(videos_dir):
            for f in files:
                if f.lower().endswith(".yuv") or f.lower().endswith(".y4m"):
                    rel_path = os.path.relpath(os.path.join(root, f), videos_dir)
                    class_name = os.path.basename(root)
                    video_files.append({"filename": f, "rel_path": rel_path, "class_name": class_name, "abs_path": os.path.join(root, f)})
    video_files.sort(key=lambda x: x["rel_path"])

    if not video_files:
        print(f"Nenhum vídeo .yuv ou .y4m encontrado na pasta: {videos_dir}")
        return

    print("\n========================================")
    print("           SELEÇÃO DE VÍDEOS            ")
    print("========================================")
    for idx, v in enumerate(video_files, 1):
        print(f"[{idx}] {v['rel_path']}")
    print("========================================")
    
    vid_sel = input("Selecione os vídeos (ex: 1,2,3 ou 1-3,5): ")
    selected_vid_indices = parse_selection(vid_sel, len(video_files))
    if not selected_vid_indices:
        print("Nenhum vídeo selecionado. Saindo...")
        return
    
    selected_videos = [video_files[i-1] for i in selected_vid_indices]

    # 3. SELEÇÃO DE QP
    # Valores de QP sugeridos no AOM CTC v8.0
    qps = [85, 110, 135, 160, 185, 210, 235]
    print("\n========================================")
    print("             SELEÇÃO DE QP              ")
    print("========================================")
    for idx, qp in enumerate(qps, 1):
        print(f"[{idx}] QP {qp}")
    print("========================================")
    
    qp_sel = input("Selecione os níveis de QP (ex: 2-7 para RA/LD, ou 1,2,3...): ")
    selected_qp_indices = parse_selection(qp_sel, len(qps))
    if not selected_qp_indices:
        print("Nenhum QP selecionado. Saindo...")
        return
    
    selected_qps = [qps[i-1] for i in selected_qp_indices]

    # 4. QUANTIDADE DE FRAMES
    print("\n========================================")
    print("      QUANTIDADE DE FRAMES (--limit)    ")
    print("========================================")
    frames_input = input("Insira a quantidade de frames (ou deixe em branco para usar do cfg): ").strip()
    frames_to_encode = None
    if frames_input:
        try:
            frames_to_encode = int(frames_input)
            if frames_to_encode <= 0:
                frames_to_encode = None
        except ValueError:
            print("Entrada inválida. Usando o limite do cfg.")

    def get_total_pocs(vid_path, cfg_args, w, h, frames_to_encode):
        if frames_to_encode:
            return frames_to_encode
        for arg in cfg_args:
            if arg.startswith('--limit='):
                try:
                    return int(arg.split('=')[1])
                except:
                    pass
        if w and h:
            try:
                bit_depth_10 = any('bit-depth=10' in arg for arg in cfg_args)
                bytes_per_pixel = 3.0 if bit_depth_10 else 1.5
                return int(os.path.getsize(vid_path) / (int(w) * int(h) * bytes_per_pixel))
            except:
                pass
        return 130 # Default AVM CTC

    def get_resolution_weight(w, h):
        if w and h:
            try:
                return (int(w) * int(h)) / 108160.0
            except ValueError:
                pass
        return 1.0

    tasks = []
    total_pocs_global = 0
    total_pocs_global_weighted = 0
    # Monta a lista de tarefas
    for vid_info in selected_videos:
        vid = vid_info["filename"]
        vid_path = vid_info["abs_path"]
        class_name = vid_info["class_name"]
        
        w, h, fr = None, None, None
        if vid.lower().endswith(".yuv"):
            match = re.search(r'_(\d+)x(\d+)_(\d+)\.yuv$', vid, re.IGNORECASE)
            if match:
                w = match.group(1)
                h = match.group(2)
                fr = match.group(3)
        
        base_name = os.path.splitext(vid)[0]

        for qp in selected_qps:
            bin_out = os.path.join(bin_dir, f"{base_name}_QP{qp}.obu")
            report_out = os.path.join(reports_dir, f"{base_name}_QP{qp}.log")
            
            cmd = [avm_bin]
            
            for arg in cfg_args:
                if arg.startswith('--qp='):
                    continue
                cmd.append(arg)
                
            # Load class config if exists
            class_cfg_path = os.path.join(cfg_dir, f"class_{class_name}.cfg")
            if os.path.exists(class_cfg_path):
                with open(class_cfg_path, 'r') as f_class:
                    class_args = f_class.read().replace('\n', ' ').split()
                    cmd.extend(class_args)
            
            cmd.append(f"--qp={qp}")
            cmd.extend(["-o", bin_out])
            
            if w and h:
                cmd.extend(["--width=" + w, "--height=" + h])
            if fr:
                cmd.extend(["--fps=" + fr + "/1"])
                
            if frames_to_encode:
                # Remove any existing --limit
                cmd = [a for a in cmd if not a.startswith("--limit=")]
                cmd.append(f"--limit={frames_to_encode}")
            
            if extra_args:
                cmd.extend(extra_args.split())

            cmd.append(vid_path) # Input file is the last argument

            task_pocs = get_total_pocs(vid_path, cfg_args, w, h, frames_to_encode)
            res_weight = get_resolution_weight(w, h)
            weight = 1 * res_weight # Simplified weight
            
            total_pocs_global += task_pocs
            total_pocs_global_weighted += (task_pocs * weight)
            tasks.append((vid, qp, cmd, report_out, task_pocs, weight))

    total_tasks = len(tasks)
    if total_tasks == 0:
        print("Nenhuma tarefa para executar.")
        return

    print(f"\n========================================")
    print(f" Total de {total_tasks} execuções programadas.")
    print(f"========================================\n")
    
    threads_avail = os.cpu_count()-1
    if threads_avail is None:
        threads_avail = 4
    
    print(f"--> Iniciando execuções com até {threads_avail} threads em paralelo...\n")

    completed_pocs_global = 0
    completed_pocs_global_weighted = 0
    results_summaries = {}
    lock = threading.Lock()
    
    def update_bar():
        percent = (completed_pocs_global_weighted / total_pocs_global_weighted) * 100 if total_pocs_global_weighted else 0
        bar_len = 40
        filled = int(bar_len * percent // 100)
        bar = '█' * filled + '-' * (bar_len - filled)
        sys.stdout.write(f"\r\033[K[ Progresso Global: |{bar}| {percent:.1f}% ({completed_pocs_global}/{total_pocs_global} POCs) ]")
        sys.stdout.flush()

    def print_msg(msg):
        with lock:
            sys.stdout.write("\r\033[K")
            sys.stdout.write(msg + "\n")
            update_bar()

    # Imprime a barra inicial em 0%
    update_bar()

    def run_task(task):
        nonlocal completed_pocs_global, completed_pocs_global_weighted
        vid, qp, cmd, report_out, task_total_pocs, weight = task
        task_id = f"{vid[:12]}_Q{qp}"
        
        print_msg(f"[ Iniciando ] {task_id}")
            
        task_pocs_done = 0
        try:
            with open(report_out, "w") as f_out:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in process.stdout:
                    f_out.write(line)
                    f_out.flush() # Salva imediatamente no arquivo em disco
                    
                    # AOM output parsing for progress: e.g. "Pass 1/1 frame  10/15" or similar
                    if "frame" in line.lower() and "/" in line:
                        with lock:
                            completed_pocs_global += 1
                            completed_pocs_global_weighted += weight
                            task_pocs_done += 1
                        print_msg(f"[{task_id}] {line.strip()}")
                process.wait()
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, cmd)
            status = "Sucesso"
        except Exception as e:
            status = f"Erro: {str(e)}"
            
        summary = f"[{task_id}] Finalizado com: {status}\n"
        if status == "Sucesso":
            try:
                with open(report_out, "r") as f_in:
                    lines = f_in.readlines()
                    # Print the last few lines which usually contain the encoding stats
                    summary += "".join(lines[-10:])
            except Exception:
                pass

        with lock:
            remaining = task_total_pocs - task_pocs_done
            if remaining > 0:
                completed_pocs_global += remaining
                completed_pocs_global_weighted += (remaining * weight)
            
            sys.stdout.write("\r\033[K")
            sys.stdout.write(f"========================================\n")
            sys.stdout.write(f"[ Concluído ] {task_id}\n")
            sys.stdout.write(f"========================================\n")
            sys.stdout.write(summary)
            if not summary.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.write("========================================\n\n")
            results_summaries[task_id] = summary
            update_bar()

    # Executa usando ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads_avail) as executor:
        list(executor.map(run_task, tasks))
        
    print_msg("\n========================================")
    print_msg("    Todas as execuções finalizadas!     ")
    print_msg("========================================")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecução cancelada pelo usuário.")
        sys.exit(1)
