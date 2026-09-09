#################### START OF FILE: ui_builder.py ####################

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
    """Builds the React frontend or generates the resilient standalone WebRTC client."""
    ui_dir = os.path.join(src_dir, "ui")
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_public_dir = os.path.join(ui_dir, "public")

    if not os.path.isdir(ui_dir):
        return True

    os.makedirs(ui_build_dir, exist_ok=True)

    log("Building React frontend...")
    if pbar: pbar.update(10, task="Building UI", detail="Checking frontend assets...")

    build_success = False

    # Check for npm or yarn first if available
    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
    yarn_cmd = shutil.which("yarn.cmd") or shutil.which("yarn")

    if yarn_cmd and os.path.isfile(os.path.join(ui_dir, "yarn.lock")):
        if pbar: pbar.update(20, task="Building UI", detail="Running yarn build...")
        try:
            res = subprocess.run([yarn_cmd, "build"], cwd=ui_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with Yarn.")
        except Exception:
            pass

    if not build_success and npm_cmd and os.path.isdir(os.path.join(ui_dir, "node_modules")):
        if pbar: pbar.update(25, task="Building UI", detail="Running npm run build...")
        try:
            res = subprocess.run([npm_cmd, "run", "build"], cwd=ui_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and is_real_ui_build(ui_dir):
                build_success = True
                log("Frontend UI built successfully with npm.")
        except Exception:
            pass

    if not build_success and deno_cmd:
        if pbar: pbar.update(30, task="Building UI", detail="Preparing Vite bundler...")
        try:
            fix_broken_vite_shims(ui_dir)
            fix_deno_windows_node_modules(ui_dir)
            cli_js = find_vite_cli(ui_dir)
            if cli_js:
                res = subprocess.run([deno_cmd, "run", "-A", cli_js, "build"], cwd=ui_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
                if res.returncode == 0 and is_real_ui_build(ui_dir):
                    build_success = True
                    log("Frontend UI built successfully with Deno Vite CLI.")
        except Exception:
            pass

    if not build_success:
        if pbar: pbar.update(35, task="Building UI", detail="Applying resilient WebRTC client...")
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