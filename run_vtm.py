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
            "vtm_binary": "../VTM/VTM_files/bin/EncoderAppStaticd",
            "cfg_dir": "../VTM/VTM_files/cfg",
            "per_sequence_dir": "../VTM/VTM_files/cfg/per-sequence",
            "videos_dir": "../VTM/videos_referencia",
            "bin_output_dir": "../VTM/bin_outputs",
            "reports_dir": "../VTM/relatorios_execucao",
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

    vtm_bin = config.get("vtm_binary", "")
    cfg_dir = config.get("cfg_dir", "")
    seq_dir = config.get("per_sequence_dir", "")
    videos_dir = config.get("videos_dir", "")
    bin_dir = config.get("bin_output_dir", "")
    reports_dir = config.get("reports_dir", "")
    extra_args = config.get("extra_args", "")

    if not os.path.exists(vtm_bin):
        print(f"Erro: Binário do VTM não encontrado: {vtm_bin}")
        print("Verifique o caminho no config.json.")
        return

    # Cria pastas de saída caso não existam
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)

    # 1. SELEÇÃO DO CFG PRINCIPAL
    main_cfgs = []
    if os.path.exists(cfg_dir):
        for f in os.listdir(cfg_dir):
            if f.lower().endswith(".cfg") and os.path.isfile(os.path.join(cfg_dir, f)):
                main_cfgs.append(f)
    main_cfgs.sort()

    if not main_cfgs:
        print(f"Nenhum arquivo .cfg principal encontrado em: {cfg_dir}")
        return

    print("========================================")
    print("        SELEÇÃO DO CFG PRINCIPAL        ")
    print("========================================")
    for idx, cfg in enumerate(main_cfgs, 1):
        print(f"[{idx}] {cfg}")
    print("========================================")
    
    while True:
        try:
            sel = int(input("Selecione o CFG principal (digite o número): "))
            if 1 <= sel <= len(main_cfgs):
                selected_main_cfg = os.path.join(cfg_dir, main_cfgs[sel-1])
                break
            else:
                print("Número fora da lista.")
        except ValueError:
            print("Entrada inválida. Digite um número.")

    # 2. SELEÇÃO DE VÍDEOS
    video_files = []
    if os.path.exists(videos_dir):
        for f in os.listdir(videos_dir):
            if f.lower().endswith(".yuv"):
                video_files.append(f)
    video_files.sort()

    if not video_files:
        print(f"Nenhum vídeo .yuv encontrado na pasta: {videos_dir}")
        return

    print("\n========================================")
    print("           SELEÇÃO DE VÍDEOS            ")
    print("========================================")
    for idx, v in enumerate(video_files, 1):
        print(f"[{idx}] {v}")
    print("========================================")
    
    vid_sel = input("Selecione os vídeos (ex: 1,2,3 ou 1-3,5): ")
    selected_vid_indices = parse_selection(vid_sel, len(video_files))
    if not selected_vid_indices:
        print("Nenhum vídeo selecionado. Saindo...")
        return
    
    selected_videos = [video_files[i-1] for i in selected_vid_indices]

    # 3. SELEÇÃO DE CFG PER-SEQUENCE PARA CADA VÍDEO
    seq_cfgs = []
    if os.path.exists(seq_dir):
        for f in os.listdir(seq_dir):
            if f.lower().endswith(".cfg"):
                seq_cfgs.append(f)
    seq_cfgs.sort()

    print("\n========================================")
    print("      SELEÇÃO DE CFG PER-SEQUENCE       ")
    print("========================================")
    for idx, cfg in enumerate(seq_cfgs, 1):
        print(f"[{idx}] {cfg}")
    print("========================================")

    video_seq_cfg_map = {}
    for vid in selected_videos:
        base_name = vid.split('_')[0]
        suggested_idx = None
        for idx, cfg in enumerate(seq_cfgs, 1):
            if cfg.lower().startswith(base_name.lower()):
                suggested_idx = idx
                break
        
        prompt = f"Para o vídeo '{vid}', escolha o CFG per-sequence"
        if suggested_idx:
            prompt += f" (Enter para usar [{suggested_idx}] {seq_cfgs[suggested_idx-1]}): "
        else:
            prompt += " (digite o número): "
        
        while True:
            sel = input(prompt).strip()
            if not sel and suggested_idx:
                video_seq_cfg_map[vid] = os.path.join(seq_dir, seq_cfgs[suggested_idx-1])
                break
            try:
                sel_int = int(sel)
                if 1 <= sel_int <= len(seq_cfgs):
                    video_seq_cfg_map[vid] = os.path.join(seq_dir, seq_cfgs[sel_int-1])
                    break
                else:
                    print("Número fora da lista.")
            except ValueError:
                if sel:
                    print("Entrada inválida. Digite um número.")
                else:
                    print("Você deve digitar um número, pois não foi possível encontrar uma sugestão automática.")

    # 4. SELEÇÃO DE QP
    qps = [22, 27, 32, 37]
    print("\n========================================")
    print("             SELEÇÃO DE QP              ")
    print("========================================")
    for idx, qp in enumerate(qps, 1):
        print(f"[{idx}] QP {qp}")
    print("========================================")
    
    qp_sel = input("Selecione os níveis de QP (ex: 1,2,3,4 ou 1-4): ")
    selected_qp_indices = parse_selection(qp_sel, len(qps))
    if not selected_qp_indices:
        print("Nenhum QP selecionado. Saindo...")
        return
    
    selected_qps = [qps[i-1] for i in selected_qp_indices]

    # 5. QUANTIDADE DE FRAMES
    print("\n========================================")
    print("      QUANTIDADE DE FRAMES (-f)         ")
    print("========================================")
    frames_input = input("Insira a quantidade de frames (ou deixe em branco para codificar tudo): ").strip()
    frames_to_encode = None
    if frames_input:
        try:
            frames_to_encode = int(frames_input)
            if frames_to_encode <= 0:
                frames_to_encode = None
        except ValueError:
            print("Entrada inválida. Todos os frames serão codificados.")

    def get_total_pocs(vid_path, vid_seq_cfg, w, h, frames_to_encode):
        if frames_to_encode:
            return frames_to_encode
        try:
            with open(vid_seq_cfg, "r") as f:
                for line in f:
                    if "FramesToBeEncoded" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            return int(parts[1].split()[0])
        except:
            pass
        if w and h:
            try:
                return int(os.path.getsize(vid_path) / (int(w) * int(h) * 1.5))
            except:
                pass
        return 100 # Default fallback se não conseguir achar

    tasks = []
    total_pocs_global = 0
    # Monta a lista de tarefas
    for vid in selected_videos:
        match = re.search(r'_(\d+)x(\d+)_(\d+)\.yuv$', vid, re.IGNORECASE)
        w, h, fr = None, None, None
        if match:
            w = match.group(1)
            h = match.group(2)
            fr = match.group(3)
        
        vid_path = os.path.join(videos_dir, vid)
        base_name = os.path.splitext(vid)[0]
        vid_seq_cfg = video_seq_cfg_map[vid]

        for qp in selected_qps:
            bin_out = os.path.join(bin_dir, f"{base_name}_QP{qp}.bin")
            report_out = os.path.join(reports_dir, f"{base_name}_QP{qp}.log")
            
            cmd = [
                vtm_bin,
                "-c", selected_main_cfg,
                "-c", vid_seq_cfg,
                "-i", vid_path,
                "-q", str(qp),
                "-b", bin_out
            ]
            
            if w and h:
                cmd.extend(["-wdt", w, "-hgt", h])
            if fr:
                cmd.extend(["-fr", fr])
            if frames_to_encode:
                cmd.extend(["-f", str(frames_to_encode)])
            
            if extra_args:
                cmd.extend(extra_args.split())

            task_pocs = get_total_pocs(vid_path, vid_seq_cfg, w, h, frames_to_encode)
            total_pocs_global += task_pocs
            tasks.append((vid, qp, cmd, report_out, task_pocs))

    total_tasks = len(tasks)
    print(f"\n========================================")
    print(f" Total de {total_tasks} execuções programadas.")
    print(f"========================================\n")
    
    threads_avail = os.cpu_count()-1
    if threads_avail is None:
        threads_avail = 4
    
    print(f"--> Iniciando execuções com até {threads_avail} threads em paralelo...\n")

    completed_pocs_global = 0
    results_summaries = {}
    lock = threading.Lock()
    
    def update_bar():
        percent = (completed_pocs_global / total_pocs_global) * 100 if total_pocs_global else 0
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
        nonlocal completed_pocs_global
        vid, qp, cmd, report_out, task_total_pocs = task
        task_id = f"{vid[:12]}_Q{qp}"
        
        print_msg(f"[ Iniciando ] {task_id}")
            
        task_pocs_done = 0
        try:
            with open(report_out, "w") as f_out:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in process.stdout:
                    f_out.write(line)
                    f_out.flush() # Salva imediatamente no arquivo em disco
                    # Filtra a impressão no terminal para mostrar apenas o progresso (POC)
                    if line.lstrip().startswith("POC") or "POC " in line:
                        with lock:
                            completed_pocs_global += 1
                            task_pocs_done += 1
                        print_msg(f"[{task_id}] {line.strip()}")
                process.wait()
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, cmd)
            status = "Sucesso"
        except Exception as e:
            status = f"Erro: {str(e)}"
            
        # Extrai o resumo final assim que a tarefa termina
        summary = f"[{task_id}] Finalizado com: {status}\n"
        if status == "Sucesso":
            try:
                with open(report_out, "r") as f_in:
                    lines = f_in.readlines()
                    for i, line in enumerate(lines):
                        # Pega o resumo (tabela PSNR, Bitrate, etc)
                        if "Total Frames |" in line or "SUMMARY" in line:
                            summary += "".join(lines[i:i+15])
                            break
            except Exception:
                pass

        with lock:
            # Compensa os POCs restantes caso a task falhe ou pule frames (ex: I-frames extra)
            remaining = task_total_pocs - task_pocs_done
            if remaining > 0:
                completed_pocs_global += remaining
            
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
