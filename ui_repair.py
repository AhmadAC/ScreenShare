# ui_repair.py 

import os
import sys
import shutil
import subprocess
from system_util import log

def safely_remove_target(dst):
    """Removes a file, symlink, junction or directory safely without raising access errors."""
    try:
        if sys.platform.startswith("win"):
            if os.path.isdir(dst):
                try:
                    os.rmdir(dst)
                    return
                except Exception:
                    pass
                try:
                    subprocess.run(
                        ["cmd", "/c", "rmdir", os.path.abspath(dst)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    if not os.path.lexists(dst):
                        return
                except Exception:
                    pass
        if os.path.islink(dst):
            os.unlink(dst)
        elif os.path.isfile(dst):
            os.remove(dst)
        elif os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
    except Exception:
        pass

def link_or_copy_dir(src, dst):
    """Safely links (via junction on Windows) or copies a directory, properly handling existing/broken targets."""
    if not os.path.isdir(src):
        return

    if os.path.isdir(dst):
        try:
            if len(os.listdir(dst)) > 0:
                return
        except Exception:
            pass

    safely_remove_target(dst)

    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)

    if sys.platform.startswith("win"):
        try:
            import _winapi
            _winapi.CreateJunction(os.path.abspath(src), os.path.abspath(dst))
            if os.path.isdir(dst):
                return
        except Exception:
            pass
        try:
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", os.path.abspath(dst), os.path.abspath(src)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if res.returncode == 0 and os.path.isdir(dst):
                return
        except Exception:
            pass

    try:
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True)
    except Exception:
        pass

def fix_deno_windows_node_modules(ui_dir):
    """Fixes Deno's missing package links on Windows by ensuring rolldown, @mui, and all dependencies are available."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    deno_store = os.path.join(nm_dir, ".deno")
    if not sys.platform.startswith("win") or not os.path.isdir(deno_store):
        return

    log("Resolving Windows package links from Deno store...")

    try:
        entries = os.listdir(deno_store)
        for entry in entries:
            inner_nm = os.path.join(deno_store, entry, "node_modules")
            if not os.path.isdir(inner_nm): 
                continue
            
            for pkg in os.listdir(inner_nm):
                pkg_path = os.path.join(inner_nm, pkg)
                if pkg.startswith("@"):
                    for subpkg in os.listdir(pkg_path):
                        sub_src = os.path.join(pkg_path, subpkg)
                        sub_dst = os.path.join(nm_dir, pkg, subpkg)
                        if os.path.isdir(sub_src) and not os.path.exists(sub_dst):
                            link_or_copy_dir(sub_src, sub_dst)
                else:
                    dst_path = os.path.join(nm_dir, pkg)
                    if os.path.isdir(pkg_path) and not os.path.exists(dst_path):
                        link_or_copy_dir(pkg_path, dst_path)
    except Exception as e:
        log(f"Notice during bulk link: {e}")

    rolldown_src = os.path.join(nm_dir, "rolldown")
    if not os.path.isdir(rolldown_src):
        for entry in os.listdir(deno_store):
            if "rolldown@" in entry:
                cand = os.path.join(deno_store, entry, "node_modules", "rolldown")
                if os.path.isdir(cand):
                    rolldown_src = cand
                    break

    at_rolldown_src = {}
    for entry in os.listdir(deno_store):
        cand_at = os.path.join(deno_store, entry, "node_modules", "@rolldown")
        if os.path.isdir(cand_at):
            for sub in os.listdir(cand_at):
                s_path = os.path.join(cand_at, sub)
                if os.path.isdir(s_path) and sub not in at_rolldown_src:
                    at_rolldown_src[sub] = s_path

    for entry in os.listdir(deno_store):
        if "vite@" in entry or entry == "vite":
            vite_root = os.path.join(deno_store, entry, "node_modules", "vite")
            targets = [
                os.path.join(vite_root, "node_modules"),
                os.path.join(vite_root, "dist", "node", "node_modules"),
                os.path.join(vite_root, "dist", "node", "chunks", "node_modules")
            ]
            for target_nm in targets:
                if rolldown_src and os.path.isdir(rolldown_src):
                    link_or_copy_dir(rolldown_src, os.path.join(target_nm, "rolldown"))
                for sub, s_path in at_rolldown_src.items():
                    link_or_copy_dir(s_path, os.path.join(target_nm, "@rolldown", sub))

def find_vite_cli(ui_dir):
    """Finds the actual Vite cli.js file in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir): return None
    
    candidates = [
        os.path.join(nm_dir, "vite", "bin", "vite.js"),
        os.path.join(nm_dir, "vite", "dist", "node", "cli.js")
    ]
    
    deno_store = os.path.join(nm_dir, ".deno")
    if os.path.isdir(deno_store):
        for entry in os.listdir(deno_store):
            if "vite@" in entry or entry == "vite":
                candidates.append(os.path.join(deno_store, entry, "node_modules", "vite", "bin", "vite.js"))
                candidates.append(os.path.join(deno_store, entry, "node_modules", "vite", "dist", "node", "cli.js"))
                
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None

def fix_broken_vite_shims(ui_dir):
    """Detects and repairs npm/cmd-shim shell scripts mistakenly written to .js files in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir): return
    cli_js = find_vite_cli(ui_dir)
    if not cli_js: return

    candidates = [
        os.path.join(nm_dir, ".bin", "vite"),
        os.path.join(nm_dir, ".bin", "vite.cmd"),
        os.path.join(nm_dir, "vite", "bin", "vite.js")
    ]
    
    deno_store = os.path.join(nm_dir, ".deno")
    if os.path.isdir(deno_store):
        for entry in os.listdir(deno_store):
            if "vite@" in entry or entry == "vite":
                candidates.append(os.path.join(deno_store, entry, "node_modules", "vite", "bin", "vite.js"))
                candidates.append(os.path.join(deno_store, entry, "node_modules", ".bin", "vite"))

    for fpath in candidates:
        if not os.path.isfile(fpath) or os.path.islink(fpath): 
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                header = fp.read(200)
            if "basedir=$(dirname" in header or "#!/bin/sh" in header:
                log(f"Repairing shell-script corruption in {fpath}...")
                rel_path = os.path.relpath(cli_js, os.path.dirname(fpath)).replace("\\", "/")
                if not rel_path.startswith("."): 
                    rel_path = "./" + rel_path
                with open(fpath, "w", encoding="utf-8") as fp:
                    fp.write(f"import '{rel_path}';\n")
                log(f"Successfully repaired {fpath} to import Vite CLI.")
        except Exception:
            pass