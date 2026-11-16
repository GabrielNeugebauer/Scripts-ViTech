#!/usr/bin/env python3
"""Installs the dav2d (AV2) and dav1d (AV1) decoders on an Android phone over adb.

Interactive (prompts in Portuguese). Paths come from config.json, next to this script.
The binaries are the AV2-Android builds (build/<decoder>-<arch>/tools/<decoder>). They go to <remote_dir>, in the
layout of AV2-Android/scripts/install_phone.sh, because Android mounts the shared storage noexec. The files to open
on the phone (streams, VERSIONS, the installation report) go to <shared_dir>, in Downloads.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "adb_binary": "adb",
    "av2_android_dir": "../../AV2-Android",
    "remote_dir": "/data/local/tmp/av2",
    "shared_dir": "/sdcard/Download/av2",
}
DECODERS = {
    "dav2d": {"label": "dav2d (AV2)", "checkasm_name": "checkasm"},
    "dav1d": {"label": "dav1d (AV1)", "checkasm_name": "checkasm-dav1d"},
}
ARCHES = ["arm64", "armv7"]


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


def menu(title, options, prompt, multi=False, default=None):
    """Numbered menu. Returns a 0-based index (or a list with multi=True); blank returns `default` if given."""
    print("\n========================================")
    print(f"  {title}")
    print("========================================")
    for idx, opt in enumerate(options, 1):
        print(f"[{idx}] {opt}")
    print("========================================")
    while True:
        answer = input(prompt).strip()
        if not answer and default is not None:
            return default
        if multi:
            sel = parse_selection(answer, len(options))
            if sel:
                return [i - 1 for i in sel]
        elif answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("Seleção inválida.")


def ask_yes(prompt, default=False):
    answer = input(prompt).strip().lower()
    if not answer:
        return default
    return answer in ("s", "sim", "y", "yes")


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
    for k, v in DEFAULT_CONFIG.items():
        config.setdefault(k, v)
    return config


class Phone:
    def __init__(self, adb, serial):
        self.adb = [adb, "-s", serial]

    def run(self, *args, check=True):
        res = subprocess.run(self.adb + list(args), stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
        return res

    def shell(self, cmd, check=True):
        res = self.run("shell", cmd, check=False)
        if check and res.returncode != 0:
            raise RuntimeError(f"no celular, '{cmd}' falhou: {(res.stderr or res.stdout).strip()}")
        return res.stdout.replace('\r', '').strip()

    def push(self, local, remote):
        self.run("push", local, remote)

    def prop(self, name):
        return self.shell(f"getprop {name}", check=False)


def list_devices(adb):
    out = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, check=True).stdout
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            info = dict(p.split(':', 1) for p in parts[2:] if ':' in p)
            devices.append({"serial": parts[0], "state": parts[1], "model": info.get("model", "?")})
    return devices


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def source_commit(src_dir):
    """Short commit of the decoder source, with -dirty when it has local changes."""
    try:
        commit = subprocess.run(["git", "-C", src_dir, "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", src_dir, "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def verify_dav2d_streams(phone, base, remote, shared, say):
    """Decodes the dav2d-test-data AVM streams (pushed to <shared>/streams) and checks each one's MD5."""
    data = os.path.join(base, "src", "dav2d-test-data", "avm")
    meson = os.path.join(data, "meson.build")
    if not os.path.isfile(meson):
        say(f"  {meson} não existe: rode AV2-Android/scripts/fetch_sources.sh dav2d-test-data")
        return
    with open(meson) as f:
        streams = re.findall(r"files\('([^']+)'\),\s*'([0-9a-f]{32})'", f.read())
    phone.shell(f"mkdir -p {shared}/streams")
    passed = 0
    for name, md5 in streams:
        phone.push(os.path.join(data, name), f"{shared}/streams/{name}")
        ok = phone.run("shell", f"{remote}/dav2d -q --threads 1 --filmgrain=1 -i {shared}/streams/{name} "
                                f"--verify {md5}", check=False).returncode == 0
        passed += ok
        say(f"  {'PASS' if ok else 'FAIL'} {name}")
    say(f"  Streams: {passed} de {len(streams)} passaram")


def main():
    os.chdir(HERE)
    config = load_config()
    if config is None:
        return
    adb, remote = config["adb_binary"], config["remote_dir"].rstrip('/')
    shared = config["shared_dir"].rstrip('/')
    base = os.path.abspath(config["av2_android_dir"])
    if not os.path.isdir(os.path.join(base, "build")):
        print(f"Erro: {base}/build não existe. Verifique av2_android_dir no config.json.")
        return

    # 1. CELULAR
    try:
        devices = list_devices(adb)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"Erro ao rodar '{adb} devices': {e}")
        return
    ready = [d for d in devices if d["state"] == "device"]
    for d in devices:
        if d["state"] != "device":
            print(f"Aviso: {d['serial']} está '{d['state']}' (autorize a depuração USB no celular).")
    if not ready:
        print("Nenhum celular conectado. Conecte por USB com a depuração USB ativada.")
        return
    dev = ready[menu("CELULAR", [f"{d['model']}  ({d['serial']})" for d in ready],
                     "Selecione o celular (em branco = 1): ", default=0)]
    phone = Phone(adb, dev["serial"])
    abilist = phone.prop("ro.product.cpu.abilist")
    print(f"\n{phone.prop('ro.product.manufacturer')} {phone.prop('ro.product.model')}, "
          f"Android {phone.prop('ro.build.version.release')}, SoC {phone.prop('ro.soc.model') or '?'}, "
          f"ABIs {abilist}")

    # 2. ARQUITETURA
    detected = 0 if "arm64-v8a" in abilist else 1
    arch = ARCHES[menu("ARQUITETURA", [a + ("   (detectada)" if i == detected else "")
                                       for i, a in enumerate(ARCHES)],
                       f"Selecione a arquitetura (em branco = {ARCHES[detected]}): ", default=detected)]

    # 3. DECODIFICADORES
    builds = {}
    rows = []
    for dec in DECODERS:
        binary = os.path.join(base, "build", f"{dec}-{arch}", "tools", dec)
        checkasm = os.path.join(base, "build", f"{dec}-{arch}-checkasm", "tests", "checkasm")
        builds[dec] = {"bin": binary if os.path.isfile(binary) else None,
                       "checkasm": checkasm if os.path.isfile(checkasm) else None,
                       "commit": source_commit(os.path.join(base, "src", dec))}
        b = builds[dec]
        status = (f"commit {b['commit']}" + ("" if b["checkasm"] else ", sem checkasm")) if b["bin"] \
            else f"não compilado (AV2-Android/scripts/build_{dec}.sh {arch})"
        rows.append(f"{DECODERS[dec]['label']:<13} {status}")
    available = [i for i, dec in enumerate(DECODERS) if builds[dec]["bin"]]
    if not available:
        print(f"\nNenhum decodificador compilado para {arch}. Rode AV2-Android/scripts/build_dav2d.sh "
              f"e build_dav1d.sh primeiro.")
        return
    picked = menu("DECODIFICADORES", rows, "Selecione (ex: 1,2; em branco = todos os compilados): ",
                  multi=True, default=available)
    names = list(DECODERS)
    chosen = []
    for i in picked:
        if builds[names[i]]["bin"]:
            chosen.append(names[i])
        else:
            print(f"Aviso: {names[i]} não está compilado para {arch}; ignorado.")
    if not chosen:
        return

    # 4. OPÇÕES
    with_checkasm = ask_yes("\nInstalar também o checkasm (testes das rotinas em assembly)? [S/n]: ", default=True)
    run_checkasm = with_checkasm and ask_yes("Rodar o checkasm depois de instalar? [s/N]: ")
    verify_streams = "dav2d" in chosen and ask_yes(
        "Decodificar os streams de conformidade do dav2d-test-data e conferir o MD5? [S/n]: ", default=True)

    print("\n========================================")
    print(f" Destino: {dev['model']} ({dev['serial']}), {arch}")
    print(f" Executáveis em {remote}; arquivos acessíveis em {shared}")
    print(f" Decodificadores: {', '.join(chosen)}" + (" + checkasm" if with_checkasm else ""))
    print("========================================")
    if not ask_yes("Instalar? [s/N]: "):
        return

    # 5. INSTALAÇÃO
    try:
        phone.shell(f"mkdir -p {remote}/streams {shared}")
        installed = []
        for dec in chosen:
            b = builds[dec]
            files = [(b["bin"], f"{remote}/{dec}")]
            if with_checkasm:
                if b["checkasm"]:
                    files.append((b["checkasm"], f"{remote}/{DECODERS[dec]['checkasm_name']}"))
                else:
                    print(f"Aviso: checkasm do {dec} não compilado; instalando só o decodificador.")
            for local, target in files:
                print(f"[ Enviando ] {os.path.relpath(local, base)} -> {target}")
                phone.push(local, target)
                phone.shell(f"chmod 755 {target}")
                remote_hash = phone.shell(f"sha256sum {target}").split()[0]
                if remote_hash != sha256(local):
                    raise RuntimeError(f"{target}: SHA-256 no celular difere do arquivo local")
            installed.append(dec)

        # VERSIONS: one line per decoder (name, commit, arch, date); lines of other decoders are kept.
        old = phone.shell(f"cat {remote}/VERSIONS 2>/dev/null", check=False).splitlines()
        now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        lines = [l for l in old if l.strip() and l.split()[0] not in installed]
        lines += [f"{dec} {builds[dec]['commit']} {arch} {now}" for dec in installed]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("\n".join(sorted(lines)) + "\n")
        try:
            phone.push(tmp.name, f"{remote}/VERSIONS")
            phone.push(tmp.name, f"{shared}/VERSIONS.txt")
        finally:
            os.unlink(tmp.name)
    except RuntimeError as e:
        print(f"\nErro: {e}")
        sys.exit(1)

    # 6. VERIFICAÇÃO (também salva em <shared>/instalacao_<data>.txt)
    report = [f"{dev['model']} ({dev['serial']}), {arch}, {now}", f"Executáveis em {remote}", ""]

    def say(msg):
        print(msg)
        report.append(msg)

    print("\n========================================")
    print("              VERIFICAÇÃO               ")
    print("========================================")
    for dec in installed:
        say(f"{dec}: {phone.shell(f'{remote}/{dec} --version 2>&1', check=False)}")
    say(f"\nVERSIONS:\n{phone.shell(f'cat {remote}/VERSIONS', check=False)}")
    if verify_streams:
        say("\ndav2d-test-data:")
        verify_dav2d_streams(phone, base, remote, shared, say)
    if run_checkasm:
        for dec in installed:
            name = DECODERS[dec]["checkasm_name"]
            if builds[dec]["checkasm"]:
                print(f"\n{name} (pode levar alguns minutos)...")
                out = phone.shell(f"{remote}/{name} 2>&1", check=False).splitlines()
                say(f"\n{name}: " + (out[-1] if out else "sem saída"))
    report_name = f"instalacao_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(report) + "\n")
    try:
        phone.push(tmp.name, f"{shared}/{report_name}")
    finally:
        os.unlink(tmp.name)
    print("\n========================================")
    print("        Instalação finalizada!          ")
    print(f"  Relatório no celular: {shared}/{report_name}")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecução cancelada pelo usuário.")
        sys.exit(1)
