#!/usr/bin/env python3
"""
windows_cleanup.py — Limpeza profunda do Windows
Uso: python windows_cleanup.py [--aggressive] [--dry-run]
Modo dry-run: mostra o que seria limpo sem apagar nada.
Modo agressivo: limpa shadow copies, WinSxS backup, SysMain cache.
Requer execucao como Administrador para acoes avancadas.
"""

import os
import sys
import shutil
import subprocess
import glob
import ctypes
import tempfile
import time
from pathlib import Path

# --- Utilitarios -------------------------------------------------

BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

freed_bytes = 0
dry_run = False
aggressive = False


def log_info(msg):
    print(f"{BLUE}[INFO]{RESET} {msg}")


def log_ok(msg, size=0):
    global freed_bytes
    freed_bytes += size
    print(f"{GREEN}[OK]{RESET} {msg}" + (f" ({_fmt(size)} liberados)" if size else ""))


def log_warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def log_error(msg):
    print(f"{RED}[ERRO]{RESET} {msg}")


def _fmt(bytes_val):
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.2f} TB"


def get_size(path):
    """Retorna tamanho total de um caminho (arquivo ou pasta)."""
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except (OSError, PermissionError):
                pass
    return total


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def safe_rmtree(path, desc=""):
    global freed_bytes
    p = Path(path)
    if not p.exists():
        return
    sz = get_size(p)
    label = desc or str(p)
    if dry_run:
        log_ok(f"[DRY-RUN] Apagaria: {label}", sz)
        return
    try:
        shutil.rmtree(str(p), ignore_errors=False)
        if not p.exists():
            log_ok(f"Apagado: {label}", sz)
        else:
            # Tenta de novo com retry
            for _ in range(3):
                time.sleep(0.5)
                try:
                    shutil.rmtree(str(p), ignore_errors=False)
                    if not p.exists():
                        log_ok(f"Apagado (retry): {label}", sz)
                        return
                except Exception:
                    pass
            log_warn(f"Nao foi possivel apagar tudo: {label} (arquivos em uso)")
    except PermissionError:
        log_warn(f"Permissao negada: {label}")
    except Exception as e:
        log_warn(f"Erro ao apagar {label}: {e}")


def safe_rmfile(path, desc=""):
    global freed_bytes
    p = Path(path)
    if not p.exists():
        return
    sz = get_size(p)
    label = desc or str(p)
    if dry_run:
        log_ok(f"[DRY-RUN] Apagaria: {label}", sz)
        return
    try:
        p.unlink()
        log_ok(f"Apagado: {label}", sz)
    except Exception as e:
        log_warn(f"Erro ao apagar {label}: {e}")


def run_cmd(cmd, desc=""):
    if dry_run:
        log_info(f"[DRY-RUN] Comando: {cmd}")
        return True, ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=120)
        if r.returncode == 0:
            log_ok(f"Comando executado: {desc or cmd}")
        else:
            log_warn(f"Comando retornou {r.returncode}: {desc or cmd}\n{r.stderr.strip()}")
        return r.returncode == 0, r.stdout.strip()
    except subprocess.TimeoutExpired:
        log_warn(f"Timeout no comando: {cmd}")
        return False, "timeout"
    except Exception as e:
        log_warn(f"Erro ao executar {cmd}: {e}")
        return False, str(e)


# --- Etapas de Limpeza -------------------------------------------

def clean_temp_folders():
    """Limpa pastas TEMP do usuario e do sistema."""
    log_info("Limpando pastas TEMP...")

    # TEMP do usuario
    user_temp = os.environ.get("TEMP", "")
    if user_temp:
        for item in Path(user_temp).glob("*"):
            try:
                if item.is_file():
                    safe_rmfile(item)
                else:
                    safe_rmtree(item)
            except Exception:
                pass

    # Windows Temp
    win_temp = r"C:\Windows\Temp"
    for item in Path(win_temp).glob("*"):
        try:
            if item.is_file():
                safe_rmfile(item)
            else:
                safe_rmtree(item)
        except Exception:
            pass

    # Prefetch
    prefetch = r"C:\Windows\Prefetch"
    for item in Path(prefetch).glob("*"):
        try:
            if item.is_file() and item.suffix == ".pf":
                safe_rmfile(item)
        except Exception:
            pass


def clean_recent_and_recycle():
    """Limpa arquivos recentes e lixeira."""
    log_info("Limpando Recentes e Lixeira...")

    # Recent (menu iniciar)
    recent = Path(os.environ["USERPROFILE"]) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent"
    if recent.exists():
        for item in recent.glob("*"):
            try:
                if item.is_file():
                    safe_rmfile(item)
                else:
                    safe_rmtree(item)
            except Exception:
                pass

    # Lixeira (via cmd)
    run_cmd("cmd /c rd /s /q C:\\$Recycle.bin 2>nul", "Lixeira (drive C:)")


def clean_browser_caches():
    """Limpa caches dos navegadores principais."""
    log_info("Limpando caches de navegadores...")
    user = os.environ["USERPROFILE"]

    cache_paths = [
        # Chrome
        (Path(user) / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cache", "Chrome Cache"),
        (Path(user) / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Code Cache", "Chrome Code Cache"),
        # Edge
        (Path(user) / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache", "Edge Cache"),
        (Path(user) / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data" / "Default" / "Code Cache", "Edge Code Cache"),
        # Firefox
        (Path(user) / "AppData" / "Local" / "Mozilla" / "Firefox" / "Profiles", "Firefox Cache"),
        # Brave
        (Path(user) / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Cache", "Brave Cache"),
    ]

    for path, label in cache_paths:
        safe_rmtree(path, label)


def clean_windows_update_cache():
    """Limpa cache do Windows Update (Download folder)."""
    log_info("Limpando cache do Windows Update...")
    cache = Path(r"C:\Windows\SoftwareDistribution\Download")
    for item in cache.glob("*"):
        try:
            if item.is_file():
                safe_rmfile(item)
            else:
                safe_rmtree(item)
        except Exception:
            pass


def clean_logs():
    """Limpa arquivos .log do Windows e app."""
    log_info("Limpando arquivos .log...")
    log_dirs = [
        r"C:\Windows\Logs",
        r"C:\Windows\Temp",
        os.environ.get("TEMP", ""),
    ]
    for d in log_dirs:
        p = Path(d)
        if not p.exists():
            continue
        for log_file in p.rglob("*.log"):
            try:
                safe_rmfile(log_file)
            except Exception:
                pass


def clean_dotnet_cache():
    """Limpa cache do .NET Native e assembly."""
    log_info("Limpando cache .NET...")
    user = os.environ["USERPROFILE"]
    paths = [
        Path(user) / "AppData" / "Local" / "assembly" / "dl3",
        Path(user) / "AppData" / "Local" / "Microsoft" / "CLR_v4.0" / "NativeImages",
    ]
    for p in paths:
        safe_rmtree(p)


def clean_shadow_copies():
    """Remove shadow copies (restore points) -- AGGRESSIVE."""
    log_info("Removendo Shadow Copies (pontos de restauracao)...")
    if not is_admin():
        log_warn("Requer Admin para remover shadow copies. Execute como Administrador.")
        return
    run_cmd("vssadmin delete shadows /all /quiet", "Shadow Copies")


def clean_sysmain():
    """Para e desabilita o servico SysMain (Superfetch)."""
    log_info("Desabilitando SysMain (Superfetch)...")
    if not is_admin():
        log_warn("Requer Admin para desabilitar SysMain.")
        return
    run_cmd("sc stop SysMain", "Parando SysMain")
    run_cmd("sc config SysMain start=disabled", "Desabilitando inicializacao SysMain")


def clean_winsxs_backup():
    """Limpa backups do WinSxS (componentes) -- AGGRESSIVE."""
    log_info("Limpando WinSxS (componentes)...")
    if not is_admin():
        log_warn("Requer Admin para limpeza de componentes.")
        return
    run_cmd(
        'dism /online /Cleanup-Image /StartComponentCleanup /ResetBase',
        "DISM StartComponentCleanup"
    )
    run_cmd(
        'dism /online /Cleanup-Image /SPSuperseded',
        "DISM SPSuperseded"
    )


def clean_disk_cleanup():
    """Executa CleanMgr com configuracoes pre-definidas (sagerun)."""
    log_info("Executando CleanMgr...")
    run_cmd("cleanmgr /sagerun:1", "CleanMgr (sagerun:1)")
    run_cmd("cleanmgr /verylowdisk", "CleanMgr (verylowdisk)")


def clean_recent_files_list():
    """Limpa lista de arquivos recentes do Explorer."""
    log_info("Limpando lista de Arquivos Recentes...")
    user = os.environ["USERPROFILE"]
    jumps = Path(user) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent" / "AutomaticDestinations"
    if jumps.exists():
        for f in jumps.glob("*"):
            safe_rmfile(f)
    mru = Path(user) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent" / "CustomDestinations"
    if mru.exists():
        for f in mru.glob("*"):
            safe_rmfile(f)


def clean_thumbs():
    """Limpa cache de thumbnails do Explorer."""
    log_info("Limpando cache de thumbnails...")
    user = os.environ["USERPROFILE"]
    thumb = Path(user) / "AppData" / "Local" / "Microsoft" / "Windows" / "Explorer"
    for f in thumb.glob("thumbcache_*.db"):
        safe_rmfile(f)


def clean_dns_cache():
    """Limpa cache DNS."""
    log_info("Limpando cache DNS...")
    run_cmd("ipconfig /flushdns", "DNS Cache")


# --- Main --------------------------------------------------------

def main():
    global dry_run, aggressive

    dry_run = "--dry-run" in sys.argv
    aggressive = "--aggressive" in sys.argv

    linha = "=" * 60
    print(f"\n{BOLD}{linha}{RESET}")
    print(f"{BOLD}{'DRY-RUN' if dry_run else 'WINDOWS CLEANUP'}{RESET}")
    if dry_run:
        print(f"{YELLOW}Apenas simulando -- nada sera apagado.{RESET}")
    print(f"{BOLD}{linha}{RESET}\n")

    start = time.time()

    # -- Etapas seguras (sempre rodam) --
    clean_temp_folders()
    clean_recent_and_recycle()
    clean_browser_caches()
    clean_windows_update_cache()
    clean_logs()
    clean_dotnet_cache()
    clean_recent_files_list()
    clean_thumbs()
    clean_dns_cache()
    clean_disk_cleanup()

    # -- Etapas agressivas --
    if aggressive:
        log_info(f"{BOLD}Modo agressivo ativado!{RESET}")
        clean_shadow_copies()
        clean_sysmain()
        clean_winsxs_backup()
    else:
        log_info("Pulei etapas agressivas (shadow copies, sysmain, winsxs). Use --aggressive para inclui-las.")

    elapsed = time.time() - start
    print(f"\n{BOLD}{linha}{RESET}")
    print(f"{GREEN}Limpeza concluida em {elapsed:.1f}s{RESET}")
    total_fmt = _fmt(freed_bytes)
    print(f"{GREEN}Total{' (simulado)' if dry_run else ''}: {total_fmt} liberados{RESET}")
    print(f"{BOLD}{linha}{RESET}\n")


if __name__ == "__main__":
    main()