# go_builder.py
import os
import sys
import shutil
import subprocess
from system_util import log, BASE_DIR
from progress_bar import ConsoleProgressBar
from ui_builder import is_real_ui_build, safely_remove_target, build_frontend_ui

def needs_rebuild(src_dir, out_bin):
    """Checks if server binary or real React production assets are missing or out of date."""
    if not os.path.isfile(out_bin):
        return True
    
    ui_dir = os.path.join(src_dir, "ui")
    if not is_real_ui_build(ui_dir):
        return True

    bin_mtime = os.path.getmtime(out_bin)
    ui_src = os.path.join(ui_dir, "src")
    if os.path.isdir(ui_src):
        for root, _, files in os.walk(ui_src):
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > bin_mtime:
                    return True
                    
    for root, dirs, files in os.walk(src_dir):
        if "ui" in dirs: 
            dirs.remove("ui")
        for f in files:
            if f.endswith(".go") and os.path.getmtime(os.path.join(root, f)) > bin_mtime:
                return True
                
    return False

def compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar=None):
    """Compiles the Go binary while streaming downloads and compilation in real-time."""
    log(f"Compiling Go binary using: {go_cmd} ...")
    if pbar:
        pbar.update(45, task="Compiling Server", detail="Initializing Go compiler...")

    safely_remove_target(out_bin)

    env = os.environ.copy()
    env["CGO_ENABLED"] = "0"
    go_bin_dir = os.path.dirname(go_cmd)
    env["PATH"] = go_bin_dir + os.pathsep + env.get("PATH", "")

    cmd = [go_cmd, "build", "-v", "-ldflags=-s -w -X main.mode=prod", "-o", out_bin, "."]

    pct = 48
    output_lines = []
    try:
        proc = subprocess.Popen(
            cmd, cwd=src_dir, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        for line in iter(proc.stdout.readline, ''):
            if not line: continue
            clean_line = line.strip()
            output_lines.append(clean_line)

            detail = ""
            if "downloading" in clean_line:
                parts = clean_line.split()
                detail = parts[1] if len(parts) > 1 else clean_line
                if "/" in detail: detail = detail.split("/")[-1]
                detail = f"Downloading {detail}"
                pct = min(82, pct + 1)
            elif clean_line.startswith("github.com/") or clean_line.startswith("golang.org/"):
                pkg_name = clean_line.split("/")[-1]
                detail = f"Compiling {pkg_name}"
                pct = min(96, pct + 1)
            else:
                detail = clean_line[:30]

            if pbar: pbar.update(pct, task="Compiling Server", detail=detail)

        proc.wait()

        if proc.returncode == 0 and os.path.isfile(out_bin):
            if not is_win:
                try: os.chmod(out_bin, 0o755)
                except Exception: pass
            if pbar: pbar.finish("ScreenShare server compiled successfully!")
            log("Server binary compilation successful.")
            return True
        else:
            if pbar: sys.stdout.write("\n")
            err_summary = "\n".join(output_lines[-25:]) if output_lines else "Unknown error"
            log(f"Go build failed with code {proc.returncode}:\n{err_summary}")
            return False
    except Exception as e:
        log(f"Failed to execute Go build: {e}")
        return False

def find_or_build_binary():
    """Locates ScreenShare binary across search directories or auto-builds it."""
    search_dirs = [
        os.path.join(BASE_DIR, "server"), BASE_DIR, os.path.join(os.getcwd(), "server"),
        os.getcwd(), os.path.join(os.path.dirname(BASE_DIR), "server"), os.path.dirname(BASE_DIR)
    ]

    is_win = sys.platform.startswith("win")
    target_names = ["ScreenShare.exe", "screenshare.exe"] if is_win else ["ScreenShare", "screenshare"]

    src_dir = None
    for d in search_dirs:
        if os.path.isfile(os.path.join(d, "main.go")):
            src_dir = d
            break

    if src_dir:
        bin_filename = "ScreenShare.exe" if is_win else "ScreenShare"
        out_bin = os.path.join(src_dir, bin_filename)
        if needs_rebuild(src_dir, out_bin):
            log("========================================")
            log("Source files modified or binary missing. Starting compilation...")
            log("========================================")
            
            pbar = ConsoleProgressBar(task="Resolving environment...")
            pbar.update(5, detail="Checking compilers...")

            deno_bins = [
                shutil.which("deno"), shutil.which("deno.exe"),
                os.path.join(os.environ.get("USERPROFILE", ""), ".deno", "bin", "deno.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "deno", "deno.exe"),
                os.path.expanduser("~/.deno/bin/deno"), os.path.expanduser("~/.local/bin/deno")
            ]
            deno_cmd = next((d for d in deno_bins if d and os.path.isfile(d)), None)

            go_bins = [
                shutil.which("go"), shutil.which("go.exe"),
                os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "Programs", "Go", "bin", "go.exe"),
                "C:\\Go\\bin\\go.exe", os.path.join(os.environ.get("USERPROFILE", ""), "go", "bin", "go.exe"),
                os.path.expanduser("~/.local/go/bin/go"), os.path.expanduser("~/go/bin/go"),
                "/usr/local/go/bin/go", "/usr/bin/go"
            ]
            go_cmd = next((g for g in go_bins if g and os.path.isfile(g)), None)

            build_frontend_ui(src_dir, deno_cmd, pbar)

            if go_cmd:
                compile_success = compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar)
                if compile_success: return out_bin
            else:
                sys.stdout.write("\n")
                log("Warning: 'go' compiler was not found on your system.")
                if is_win: log("Please install Go on Windows by running in PowerShell: winget install GoLang.Go")
                else: log("Please install Go to compile the server binary.")

    for d in search_dirs:
        for name in target_names:
            bin_path = os.path.join(d, name)
            if os.path.isfile(bin_path):
                if not is_win and not os.access(bin_path, os.X_OK):
                    try: os.chmod(bin_path, 0o755)
                    except Exception: pass
                return bin_path

    for name in target_names:
        in_path = shutil.which(name)
        if in_path: return in_path

    return None