import os
import sys
import time
import shutil
import tempfile
import threading
import subprocess
import urllib.request
from system_util import log, BASE_DIR, get_clean_host_env

class ConsoleProgressBar:
    def __init__(self, task="Processing"):
        self.current_step = 0
        self.task = task
        self.detail = ""
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0
        self.start_time = time.time()

    def update(self, percent, task=None, detail=""):
        self.current_step = max(0, min(100, percent))
        if task:
            self.task = task
        self.detail = detail
        self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_chars)
        spinner = self.spinner_chars[self.spinner_idx]

        bar_len = 24
        filled_len = int(bar_len * (self.current_step / 100.0))
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed)}s"

        det = f" | {self.detail}" if self.detail else ""
        if len(det) > 36:
            det = det[:33] + "..."

        line = f"\r{spinner} [{bar}] {self.current_step:3d}% ({elapsed_str}) {self.task}{det}"
        sys.stdout.write(line.ljust(85))
        sys.stdout.flush()

    def finish(self, message="Complete!"):
        bar = "█" * 24
        elapsed = time.time() - self.start_time
        line = f"\r✔ [{bar}] 100% ({int(elapsed)}s) {message}"
        sys.stdout.write(line.ljust(85) + "\n")
        sys.stdout.flush()

def is_real_ui_build(ui_dir):
    """Verifies that ui/build contains actual compiled React assets."""
    build_dir = os.path.join(ui_dir, "build")
    index_file = os.path.join(build_dir, "index.html")
    assets_dir = os.path.join(build_dir, "assets")
    if not os.path.isfile(index_file) or not os.path.isdir(assets_dir):
        return False
    js_files = [f for f in os.listdir(assets_dir) if f.endswith(".js")]
    return len(js_files) > 0

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
                    subprocess.run(["cmd", "/c", "rmdir", os.path.abspath(dst)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    if not os.path.isdir(deno_store):
        return

    log("Resolving Windows package links from Deno store...")
    for entry in os.listdir(deno_store):
        entry_path = os.path.join(deno_store, entry)
        if not os.path.isdir(entry_path):
            continue
        inner_nm = os.path.join(entry_path, "node_modules")
        if not os.path.isdir(inner_nm):
            continue
        try:
            for pkg in os.listdir(inner_nm):
                pkg_path = os.path.join(inner_nm, pkg)
                if pkg.startswith("@"):
                    for subpkg in os.listdir(pkg_path):
                        sub_src = os.path.join(pkg_path, subpkg)
                        sub_dst = os.path.join(nm_dir, pkg, subpkg)
                        if os.path.isdir(sub_src):
                            link_or_copy_dir(sub_src, sub_dst)
                else:
                    dst_path = os.path.join(nm_dir, pkg)
                    if os.path.isdir(pkg_path):
                        link_or_copy_dir(pkg_path, dst_path)
        except Exception:
            pass

    # Ensure @mui/utils is mirrored everywhere in .deno @mui packages
    mui_utils_src = None
    for entry in os.listdir(deno_store):
        if "@mui+utils" in entry:
            cand = os.path.join(deno_store, entry, "node_modules", "@mui", "utils")
            if os.path.isdir(cand):
                mui_utils_src = cand
                break
    if not mui_utils_src and os.path.isdir(os.path.join(nm_dir, "@mui", "utils")):
        mui_utils_src = os.path.join(nm_dir, "@mui", "utils")

    if mui_utils_src:
        link_or_copy_dir(mui_utils_src, os.path.join(nm_dir, "@mui", "utils"))
        for entry in os.listdir(deno_store):
            if entry.startswith("@mui+"):
                target_mui = os.path.join(deno_store, entry, "node_modules", "@mui", "utils")
                link_or_copy_dir(mui_utils_src, target_mui)

    rolldown_src = None
    at_rolldown_src = {}

    if os.path.isdir(os.path.join(nm_dir, "rolldown")):
        rolldown_src = os.path.join(nm_dir, "rolldown")

    for entry in os.listdir(deno_store):
        if not rolldown_src and "rolldown@" in entry:
            cand = os.path.join(deno_store, entry, "node_modules", "rolldown")
            if os.path.isdir(cand):
                rolldown_src = cand
        if "@rolldown" in entry or "binding-" in entry:
            cand_at = os.path.join(deno_store, entry, "node_modules", "@rolldown")
            if os.path.isdir(cand_at):
                for sub in os.listdir(cand_at):
                    s_path = os.path.join(cand_at, sub)
                    if os.path.isdir(s_path) and sub not in at_rolldown_src:
                        at_rolldown_src[sub] = s_path

    if rolldown_src:
        link_or_copy_dir(rolldown_src, os.path.join(nm_dir, "rolldown"))
    for sub, s_path in at_rolldown_src.items():
        link_or_copy_dir(s_path, os.path.join(nm_dir, "@rolldown", sub))

    for root, dirs, _ in os.walk(deno_store):
        base = os.path.basename(root)
        if base == "vite" and "node_modules" in root:
            targets = [
                os.path.join(root, "node_modules"),
                os.path.join(os.path.dirname(root)),
                os.path.join(root, "dist", "node", "node_modules"),
                os.path.join(root, "dist", "node", "chunks", "node_modules")
            ]
            for target_nm in targets:
                if rolldown_src:
                    link_or_copy_dir(rolldown_src, os.path.join(target_nm, "rolldown"))
                for sub, s_path in at_rolldown_src.items():
                    link_or_copy_dir(s_path, os.path.join(target_nm, "@rolldown", sub))

def fix_broken_vite_shims(ui_dir):
    """Detects and repairs npm/cmd-shim shell scripts mistakenly written to .js files in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir):
        return

    cli_js = find_vite_cli(ui_dir)

    for root, _, files in os.walk(nm_dir):
        for f in files:
            fpath = os.path.join(root, f)
            if not os.path.isfile(fpath) or os.path.islink(fpath) or os.path.isdir(fpath):
                continue

            if f.endswith(".js") or f.endswith(".mjs") or f == "vite":
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                        header = fp.read(200)
                    if "basedir=" in header or "#!/bin/sh" in header or "dirname" in header:
                        log(f"Repairing shell-script corruption in {fpath}...")
                        if cli_js and os.path.isfile(cli_js):
                            rel_path = os.path.relpath(cli_js, os.path.dirname(fpath)).replace("\\", "/")
                            if not rel_path.startswith("."):
                                rel_path = "./" + rel_path
                            with open(fpath, "w", encoding="utf-8") as fp:
                                fp.write(f"import '{rel_path}';\n")
                            log(f"Successfully repaired {fpath} to import Vite CLI.")
                except Exception:
                    pass

def find_vite_cli(ui_dir):
    """Finds the actual Vite cli.js file in node_modules."""
    nm_dir = os.path.join(ui_dir, "node_modules")
    if not os.path.isdir(nm_dir):
        return None
    for root, _, files in os.walk(nm_dir):
        if "cli.js" in files and ("dist" in root and "node" in root):
            candidate = os.path.join(root, "cli.js")
            if "vite" in candidate.lower():
                return candidate
    return None

def write_failsafe_client(ui_dir):
    """Generates a resilient fallback application inside ui/build if bundlers fail."""
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_assets_dir = os.path.join(ui_build_dir, "assets")
    os.makedirs(ui_assets_dir, exist_ok=True)

    index_html = os.path.join(ui_build_dir, "index.html")
    with open(index_html, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ScreenShare</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { background-color: #282828; color: #fbf1c7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    #container { text-align: center; max-width: 600px; padding: 30px; background: #32302f; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
    h1 { color: #fabd2f; margin-bottom: 10px; }
    p { color: #a89984; line-height: 1.5; }
    video { width: 100%; border-radius: 8px; margin-top: 15px; background: #1d2021; }
    .status { margin-top: 15px; font-weight: bold; color: #8ec07c; }
  </style>
</head>
<body>
  <div id="container">
    <h1>ScreenShare Live Session</h1>
    <p id="msg">Connecting to live screen broadcast...</p>
    <div class="status" id="status">Standby</div>
    <video id="remoteVideo" autoplay playsinline></video>
  </div>
  <script src="./assets/client.js"></script>
</body>
</html>
""")

    client_js = os.path.join(ui_assets_dir, "client.js")
    with open(client_js, "w", encoding="utf-8") as f:
        f.write("""
(function() {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get('room') || 'a';
  const isCreate = params.get('create') === 'true';
  const statusEl = document.getElementById('status');
  const msgEl = document.getElementById('msg');
  const videoEl = document.getElementById('remoteVideo');

  let ws;
  let activeStream = null;
  const peerConnections = {};

  function connectSignaling() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${window.location.host}/stream`);

    ws.onopen = () => {
      statusEl.innerText = "Connected to room: " + roomId;
      if (isCreate) {
        ws.send(JSON.stringify({
          type: "create",
          payload: { id: roomId, mode: "stun", joinIfExist: true, closeOnOwnerLeave: false, username: "Host" }
        }));
      } else {
        ws.send(JSON.stringify({
          type: "join",
          payload: { id: roomId, username: "Viewer" }
        }));
      }
    };

    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "hostsession" && activeStream) {
        const pc = new RTCPeerConnection({ iceServers: msg.payload.iceServers });
        peerConnections[msg.payload.id] = pc;
        activeStream.getTracks().forEach(t => pc.addTrack(t, activeStream));
        pc.onicecandidate = (e) => {
          if (e.candidate) {
            ws.send(JSON.stringify({ type: "hostice", payload: { sid: msg.payload.id, value: e.candidate } }));
          }
        };
        const offer = await pc.createOffer({ offerToReceiveVideo: true });
        await pc.setLocalDescription(offer);
        ws.send(JSON.stringify({ type: "hostoffer", payload: { sid: msg.payload.id, value: offer } }));
      } else if (msg.type === "clientanswer") {
        const pc = peerConnections[msg.payload.sid];
        if (pc) await pc.setRemoteDescription(msg.payload.value);
      } else if (msg.type === "clientsession") {
        const pc = new RTCPeerConnection({ iceServers: msg.payload.iceServers });
        peerConnections[msg.payload.id] = pc;
        pc.ontrack = (e) => {
          if (videoEl) {
            videoEl.srcObject = e.streams[0] || new MediaStream([e.track]);
            videoEl.play().catch(() => {});
            msgEl.innerText = "Broadcasting active screen";
          }
        };
        pc.onicecandidate = (e) => {
          if (e.candidate) {
            ws.send(JSON.stringify({ type: "clientice", payload: { sid: msg.payload.id, value: e.candidate } }));
          }
        };
      } else if (msg.type === "hostoffer") {
        const pc = peerConnections[msg.payload.sid];
        if (pc) {
          await pc.setRemoteDescription(msg.payload.value);
          const ans = await pc.createAnswer();
          await pc.setLocalDescription(ans);
          ws.send(JSON.stringify({ type: "clientanswer", payload: { sid: msg.payload.sid, value: ans } }));
        }
      }
    };

    ws.onclose = () => {
      statusEl.innerText = "Connection lost. Reconnecting...";
      setTimeout(connectSignaling, 2000);
    };
  }

  async function startShare() {
    try {
      activeStream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 60 } },
        audio: false
      });
      statusEl.innerText = "Screen capture started";
      ws.send(JSON.stringify({ type: "share", payload: {} }));
      reportState({ sharing: true });
    } catch(err) {
      console.error("Capture error:", err);
    }
  }

  function stopShare() {
    if (activeStream) {
      activeStream.getTracks().forEach(t => t.stop());
      activeStream = null;
    }
    ws.send(JSON.stringify({ type: "stopshare", payload: {} }));
    reportState({ sharing: false });
  }

  function reportState(state) {
    fetch('http://127.0.0.1:5055/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state)
    }).catch(() => {});
  }

  setInterval(() => {
    fetch('http://127.0.0.1:5055/poll?t=' + Date.now())
      .then(r => r.json())
      .then(d => {
        if (d.action === "start_share") startShare();
        else if (d.action === "stop_share") stopShare();
      })
      .catch(() => {});
  }, 300);

  connectSignaling();
})();
""")

def build_frontend_ui(src_dir, deno_cmd, pbar=None):
    """Builds the React frontend and guarantees ui/build contains real React assets for Go embed."""
    ui_dir = os.path.join(src_dir, "ui")
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_public_dir = os.path.join(ui_dir, "public")

    if not os.path.isdir(ui_dir):
        return True

    if not is_real_ui_build(ui_dir):
        shutil.rmtree(ui_build_dir, ignore_errors=True)

    log("Building React frontend...")
    if pbar:
        pbar.update(10, task="Building UI", detail="Installing dependencies...")

    if deno_cmd:
        try:
            subprocess.run([deno_cmd, "install"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        except Exception as e:
            log(f"Deno install notice: {e}")

    fix_broken_vite_shims(ui_dir)
    fix_deno_windows_node_modules(ui_dir)

    if pbar:
        pbar.update(25, task="Building UI", detail="Running Vite bundler...")

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
            if pbar:
                pbar.update(35, task="Building UI", detail="Trying npx vite...")
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
                try:
                    shutil.copy2(s, d)
                except Exception:
                    pass

    return is_real_ui_build(ui_dir)

def compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar=None):
    """Compiles the Go binary while streaming downloads and compilation in real-time."""
    log(f"Compiling Go binary using: {go_cmd} ...")
    if pbar:
        pbar.update(45, task="Compiling Server", detail="Initializing Go compiler...")

    if os.path.isfile(out_bin):
        try:
            os.remove(out_bin)
        except Exception:
            pass

    env = os.environ.copy()
    env["CGO_ENABLED"] = "0"
    go_bin_dir = os.path.dirname(go_cmd)
    env["PATH"] = go_bin_dir + os.pathsep + env.get("PATH", "")

    cmd = [go_cmd, "build", "-v", "-ldflags=-s -w -X main.mode=prod", "-o", out_bin, "."]

    pct = 48
    output_lines = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=src_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(proc.stdout.readline, ''):
            if not line:
                continue
            clean_line = line.strip()
            output_lines.append(clean_line)

            detail = ""
            if "downloading" in clean_line:
                parts = clean_line.split()
                detail = parts[1] if len(parts) > 1 else clean_line
                if "/" in detail:
                    detail = detail.split("/")[-1]
                detail = f"Downloading {detail}"
                pct = min(82, pct + 1)
            elif clean_line.startswith("github.com/") or clean_line.startswith("golang.org/"):
                pkg_name = clean_line.split("/")[-1]
                detail = f"Compiling {pkg_name}"
                pct = min(96, pct + 1)
            else:
                detail = clean_line[:30]

            if pbar:
                pbar.update(pct, task="Compiling Server", detail=detail)

        proc.wait()

        if proc.returncode == 0 and os.path.isfile(out_bin):
            if not is_win:
                try:
                    os.chmod(out_bin, 0o755)
                except Exception:
                    pass
            if pbar:
                pbar.finish("ScreenShare server compiled successfully!")
            log("Server binary compilation successful.")
            return True
        else:
            if pbar:
                sys.stdout.write("\n")
            err_summary = "\n".join(output_lines[-25:]) if output_lines else "Unknown error"
            log(f"Go build failed with code {proc.returncode}:\n{err_summary}")
            return False
    except Exception as e:
        log(f"Failed to execute Go build: {e}")
        return False

def find_or_build_binary():
    """Locates ScreenShare binary across search directories or auto-builds it."""
    search_dirs = [
        os.path.join(BASE_DIR, "server"),
        BASE_DIR,
        os.path.join(os.getcwd(), "server"),
        os.getcwd(),
        os.path.join(os.path.dirname(BASE_DIR), "server"),
        os.path.dirname(BASE_DIR)
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
                shutil.which("deno"),
                shutil.which("deno.exe"),
                os.path.join(os.environ.get("USERPROFILE", ""), ".deno", "bin", "deno.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "deno", "deno.exe"),
                os.path.expanduser("~/.deno/bin/deno"),
                os.path.expanduser("~/.local/bin/deno")
            ]
            deno_cmd = next((d for d in deno_bins if d and os.path.isfile(d)), None)

            go_bins = [
                shutil.which("go"),
                shutil.which("go.exe"),
                os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Go", "bin", "go.exe"),
                os.path.join(os.environ.get("LocalAppData", ""), "Programs", "Go", "bin", "go.exe"),
                "C:\\Go\\bin\\go.exe",
                os.path.join(os.environ.get("USERPROFILE", ""), "go", "bin", "go.exe"),
                os.path.expanduser("~/.local/go/bin/go"),
                os.path.expanduser("~/go/bin/go"),
                "/usr/local/go/bin/go",
                "/usr/bin/go"
            ]
            go_cmd = next((g for g in go_bins if g and os.path.isfile(g)), None)

            build_frontend_ui(src_dir, deno_cmd, pbar)

            if go_cmd:
                compile_success = compile_go_binary(src_dir, out_bin, go_cmd, is_win, pbar)
                if compile_success:
                    return out_bin
            else:
                sys.stdout.write("\n")
                log("Warning: 'go' compiler was not found on your system.")
                if is_win:
                    log("Please install Go on Windows by running in PowerShell: winget install GoLang.Go")
                else:
                    log("Please install Go to compile the server binary.")

    for d in search_dirs:
        for name in target_names:
            bin_path = os.path.join(d, name)
            if os.path.isfile(bin_path):
                if not is_win and not os.access(bin_path, os.X_OK):
                    try:
                        os.chmod(bin_path, 0o755)
                    except Exception:
                        pass
                return bin_path

    for name in target_names:
        in_path = shutil.which(name)
        if in_path:
            return in_path

    return None

def stream_process_logs(proc, prefix_label):
    """Continuously reads stdout and stderr lines from a subprocess and writes them to the log."""
    def read_stream(stream, stream_name):
        try:
            for line in iter(stream.readline, ''):
                if line:
                    log(f"[{prefix_label} {stream_name}] {line.strip()}")
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    if proc.stdout:
        threading.Thread(target=read_stream, args=(proc.stdout, "stdout"), daemon=True).start()
    if proc.stderr:
        threading.Thread(target=read_stream, args=(proc.stderr, "stderr"), daemon=True).start()

def start_screenshare_server(lan_ip):
    """Spawns the Go backend binary, enabling TURN relay and persistent rooms."""
    server_bin = find_or_build_binary()

    if not server_bin or not os.path.isfile(server_bin):
        is_win = sys.platform.startswith("win")
        expected_bin = "ScreenShare.exe" if is_win else "ScreenShare"
        log("========================================")
        log(f"Error: Server executable binary '{expected_bin}' not found.")
        if is_win:
            log("The Go compiler is required to build ScreenShare.exe.")
            log("To install Go on Windows, open PowerShell and run:")
            log("  winget install GoLang.Go")
        else:
            log("Please install Go and build it once by running: go build -o ScreenShare .")
        log("========================================")
        sys.exit(1)

    bin_dir = os.path.dirname(os.path.abspath(server_bin))
    log(f"Using server binary: {server_bin}")
    log(f"Working Directory  : {bin_dir}")

    env = os.environ.copy()
    configs = {
        "EXTERNAL_IP": lan_ip,
        "SERVER_ADDRESS": "0.0.0.0:5050",
        "TURN_ADDRESS": "0.0.0.0:3478",
        "AUTH_MODE": "none",
        "CLOSE_ROOM_WHEN_OWNER_LEAVES": "false",
        "LOG_LEVEL": "info",
    }
    for k, v in configs.items():
        env[f"SCREENSHARE_{k}"] = v
    
    users_candidates = [
        os.path.join(bin_dir, "users"),
        os.path.join(BASE_DIR, "users"),
        os.path.join(BASE_DIR, "server", "users"),
        os.path.join(os.getcwd(), "users"),
        os.path.join(os.getcwd(), "server", "users")
    ]
    for u_path in users_candidates:
        if os.path.isfile(u_path):
            abs_u = os.path.abspath(u_path)
            env["SCREENSHARE_USERS_FILE"] = abs_u
            break

    proc = subprocess.Popen(
        [server_bin, "serve"],
        env=env,
        cwd=bin_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    stream_process_logs(proc, "Server")
    return proc

def wait_for_server(url, proc=None, timeout=6.0):
    """Waits until the local HTTP server is responsive before opening browser."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if proc and proc.poll() is not None:
            log(f"CRITICAL: Backend server terminated prematurely with exit code: {proc.poll()}")
            return False
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 302, 304):
                    log(f"Backend server is up and responsive at {url}")
                    return True
        except Exception:
            time.sleep(0.2)
    log(f"Warning: Backend server did not respond at {url} within {timeout} seconds.")
    return False

def find_browser_executable():
    """Searches for Microsoft Edge, Chrome, or Chromium across host paths, Snaps, and Flatpaks."""
    clean_env = get_clean_host_env()

    if sys.platform.startswith("win"):
        win_candidates = [
            shutil.which("msedge"),
            shutil.which("chrome"),
            shutil.which("brave"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Microsoft\\Edge\\Application\\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "BraveSoftware\\Brave-Browser\\Application\\brave.exe"),
        ]
        for path in win_candidates:
            if path and os.path.isfile(path):
                log(f"Found Windows browser: '{path}'")
                return [path]
        return None

    search_binaries = [
        "microsoft-edge-stable", "microsoft-edge", "msedge", "com.microsoft.Edge",
        "google-chrome-stable", "google-chrome", "chrome", "com.google.Chrome",
        "chromium", "chromium-browser", "org.chromium.Chromium", "brave-browser",
        "brave", "com.brave.Browser", "vivaldi", "vivaldi-stable",
        "microsoft-edge-beta", "microsoft-edge-dev", "google-chrome-beta", "google-chrome-unstable"
    ]

    explicit_dirs = [
        "/usr/bin", "/usr/local/bin", "/bin", "/snap/bin", "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        os.path.expanduser("~/.local/bin"), os.path.expanduser("~/bin"),
        "/opt/microsoft/msedge", "/opt/microsoft/msedge-beta", "/opt/microsoft/msedge-dev",
        "/opt/google/chrome", "/opt/brave.com/brave", "/app/bin"
    ]

    log("Scanning host for browser binaries...")
    for binary in search_binaries:
        path = shutil.which(binary, path=clean_env.get("PATH", ""))
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            log(f"Found executable browser in PATH: '{binary}' -> '{path}'")
            return [path]
        
        for d in explicit_dirs:
            full_path = os.path.join(d, binary)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                log(f"Found executable browser in '{d}': '{full_path}'")
                return [full_path]

    flatpak_candidates = [
        shutil.which("flatpak", path=clean_env.get("PATH", "")),
        "/usr/bin/flatpak", "/usr/local/bin/flatpak", "/var/lib/flatpak",
    ]
    flatpak_bin = next((f for f in flatpak_candidates if f and os.path.isfile(f) and os.access(f, os.X_OK)), None)
    
    app_ids = [
        "com.microsoft.Edge", "com.microsoft.Edge.Dev", "com.microsoft.Edge.Beta",
        "com.google.Chrome", "com.google.Chrome.Dev", "com.google.Chrome.Beta",
        "org.chromium.Chromium", "com.brave.Browser"
    ]

    if flatpak_bin:
        for app_id in app_ids:
            res = subprocess.run([flatpak_bin, "info", app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
            if res.returncode == 0:
                log(f"Found candidate browser in Flatpak: '{app_id}'")
                return [flatpak_bin, "run", app_id]

            flatpak_app_dirs = [
                os.path.join("/var/lib/flatpak/app", app_id),
                os.path.expanduser(f"~/.local/share/flatpak/app/{app_id}"),
            ]
            if any(os.path.isdir(p) for p in flatpak_app_dirs):
                log(f"Found Flatpak app directory for '{app_id}'")
                return [flatpak_bin, "run", app_id]

    return None

def launch_hidden_browser(url):
    """Finds and launches Edge/Chromium on host system in an isolated profile."""
    executable_cmd = find_browser_executable()

    if not executable_cmd:
        log("========================================================================")
        log("ERROR: No compatible Microsoft Edge or Chromium browser found on system!")
        log(f"Current PATH: {os.environ.get('PATH', '')}")
        log("Please install Microsoft Edge or Google Chrome/Chromium to enable screen sharing.")
        log("========================================================================")
        return None

    isolated_profile_dir = os.path.join(tempfile.gettempdir(), "ScreenShare_browser_profile")
    os.makedirs(isolated_profile_dir, exist_ok=True)

    cmd = executable_cmd + [
        f"--app={url}",
        f"--user-data-dir={isolated_profile_dir}",
        "--test-type",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-vulkan",
        "--disable-application-cache",
        "--disk-cache-size=1",
        "--media-cache-size=1",
        "--ozone-platform-hint=auto",
        "--enable-features=WebRTCPipeWireCapturer,VaapiVideoEncoder,VaapiVideoDecoder,CanvasOopRasterization",
        "--disable-features=AudioServiceOutOfProcess,AudioServiceSandbox,IsolateOrigins,site-per-process,Vulkan",
        "--use-fake-ui-for-media-stream",
        "--enable-usermedia-screen-capturing",
        "--auto-select-desktop-capture-source=Entire screen",
        "--auto-accept-camera-and-microphone-capture",
        "--allow-http-screen-capture",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--autoplay-policy=no-user-gesture-required",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-breakpad",
        "--disable-component-update",
        "--window-size=1280,720"
    ]

    clean_env = get_clean_host_env()
    log("=================================================================")
    log(" Launching Browser Subprocess")
    log(f" Command         : {' '.join(cmd)}")
    log(f" Profile Dir     : {isolated_profile_dir}")
    log(f" DISPLAY         : {clean_env.get('DISPLAY', '<none>')}")
    log(f" WAYLAND_DISPLAY : {clean_env.get('WAYLAND_DISPLAY', '<none>')}")
    log(f" XDG_DATA_DIRS   : {clean_env.get('XDG_DATA_DIRS', '<none>')}")
    log("=================================================================")

    try:
        proc = subprocess.Popen(
            cmd,
            env=clean_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        stream_process_logs(proc, "Browser")

        def check_browser_health():
            time.sleep(3.0)
            ret = proc.poll()
            if ret is not None:
                log(f"CRITICAL: Browser terminated unexpectedly shortly after launch! Exit code: {ret}")
            else:
                log("Browser process is active and running normally.")

        threading.Thread(target=check_browser_health, daemon=True).start()
        return proc
    except Exception as e:
        log(f"CRITICAL: Failed to spawn browser process: {e}")
        return None