#  ui_builder.py

import os
import sys
import shutil
import subprocess
from system_util import log
from ui_repair import (
    safely_remove_target,
    fix_deno_windows_node_modules,
    fix_broken_vite_shims,
    find_vite_cli
)
from ui_failsafe import write_failsafe_client

def is_real_ui_build(ui_dir):
    """Verifies that ui/build contains compiled assets and valid index.html."""
    build_dir = os.path.join(ui_dir, "build")
    index_file = os.path.join(build_dir, "index.html")
    assets_dir = os.path.join(build_dir, "assets")
    if not os.path.isfile(index_file) or not os.path.isdir(assets_dir):
        return False
    js_files = [f for f in os.listdir(assets_dir) if f.endswith(".js")]
    return len(js_files) > 0

def build_frontend_ui(src_dir, deno_cmd, pbar=None):
    """Builds the React frontend and guarantees ui/build contains real assets for Go embed."""
    ui_dir = os.path.join(src_dir, "ui")
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_public_dir = os.path.join(ui_dir, "public")

    if not os.path.isdir(ui_dir):
        return True

    shutil.rmtree(ui_build_dir, ignore_errors=True)

    log("Building React frontend...")
    if pbar: pbar.update(10, task="Building UI", detail="Installing dependencies...")

    if deno_cmd:
        try:
            subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        except Exception as e: 
            log(f"Deno install notice: {e}")

    fix_broken_vite_shims(ui_dir)
    fix_deno_windows_node_modules(ui_dir)

    if pbar: pbar.update(25, task="Building UI", detail="Running Vite bundler...")

    build_success = False
    cli_js = find_vite_cli(ui_dir)
    
    if cli_js and deno_cmd:
        try:
            log(f"Invoking Vite CLI directly: {cli_js}")
            res = subprocess.run([deno_cmd, "run", "-A", cli_js, "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with direct Vite CLI.")
            else: 
                log(f"Direct Vite CLI notice: {res.stderr or res.stdout}")
        except Exception as e: 
            log(f"Direct Vite CLI error: {e}")

    if not build_success and deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "task", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with Deno task.")
            else: 
                log(f"Deno task build notice: {res.stderr or res.stdout}")
        except Exception as e: 
            log(f"Deno task build notice: {e}")

    if not build_success and deno_cmd:
        try:
            res = subprocess.run([deno_cmd, "run", "-A", "npm:vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with Deno npm:vite.")
            else: 
                log(f"Deno npm:vite notice: {res.stderr or res.stdout}")
        except Exception as e: 
            log(f"Deno npm:vite notice: {e}")

    if not build_success:
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            if pbar: pbar.update(35, task="Building UI", detail="Trying npx vite...")
            try:
                res = subprocess.run([npx_cmd, "--yes", "vite", "build"], cwd=ui_dir, capture_output=True, text=True, timeout=90)
                if res.returncode == 0 and is_real_ui_build(ui_dir):
                    build_success = True
                    log("Frontend UI built successfully with npx vite.")
            except Exception as e: 
                log(f"npx vite notice: {e}")

    if not is_real_ui_build(ui_dir):
        log("Notice: Vite did not emit assets, writing resilient fallback client...")
        write_failsafe_client(ui_dir)

    os.makedirs(ui_build_dir, exist_ok=True)

    if os.path.isdir(ui_public_dir):
        for item in os.listdir(ui_public_dir):
            s = os.path.join(ui_public_dir, item)
            d = os.path.join(ui_build_dir, item)
            if os.path.isfile(s) and not os.path.exists(d):
                try: shutil.copy2(s, d)
                except Exception: pass

    return is_real_ui_build(ui_dir)