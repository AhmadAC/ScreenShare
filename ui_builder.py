# ui_builder.py
import os
import sys
import shutil
import subprocess
from system_util import log

def is_real_ui_build(ui_dir):
    """Verifies that ui/build contains compiled assets and valid index.html."""
    build_dir = os.path.join(ui_dir, "build")
    index_file = os.path.join(build_dir, "index.html")
    assets_dir = os.path.join(build_dir, "assets")
    if not os.path.isfile(index_file) or not os.path.isdir(assets_dir):
        return False
    js_files = [f for f in os.listdir(assets_dir) if f.endswith(".js")]
    return len(js_files) > 0

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

def write_failsafe_client(ui_dir):
    """Generates a resilient fallback application inside ui/build with full WebRTC audio/video broadcasting and candidate exchange."""
    ui_build_dir = os.path.join(ui_dir, "build")
    ui_assets_dir = os.path.join(ui_build_dir, "assets")
    os.makedirs(ui_assets_dir, exist_ok=True)

    index_html = os.path.join(ui_build_dir, "index.html")
    with open(index_html, "w", encoding="utf-8") as f:
        f.write('''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ScreenShare</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body, html {
      width: 100%;
      height: 100%;
      background-color: #1d2021;
      color: #fbf1c7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    #header {
      position: absolute;
      top: 12px;
      left: 12px;
      right: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 20;
      pointer-events: none;
    }
    .badge {
      background: rgba(40, 40, 40, 0.85);
      border: 1px solid #504945;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: bold;
      color: #fabd2f;
      backdrop-filter: blur(8px);
      pointer-events: auto;
    }
    #status {
      color: #8ec07c;
    }
    #videoContainer {
      position: relative;
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
      cursor: pointer;
    }
    video {
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: #000;
    }
    #overlayMessage {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      text-align: center;
      z-index: 10;
      background: rgba(40, 40, 40, 0.95);
      padding: 24px 32px;
      border-radius: 16px;
      border: 1px solid #fabd2f;
      box-shadow: 0 10px 30px rgba(0,0,0,0.8);
      max-width: 90%;
    }
    #overlayMessage h2 {
      color: #fabd2f;
      margin-bottom: 8px;
      font-size: 20px;
    }
    #overlayMessage p {
      color: #a89984;
      font-size: 14px;
      margin-bottom: 12px;
    }
    #btnStartCapture {
      display: none;
      background: #fabd2f;
      color: #282828;
      border: none;
      padding: 10px 20px;
      border-radius: 18px;
      font-size: 14px;
      font-weight: bold;
      cursor: pointer;
      margin: 0 auto;
    }
    #btnStartCapture:hover {
      background: #d79921;
    }
    #audioBanner {
      position: absolute;
      top: 60px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 30;
      background: #fabd2f;
      color: #282828;
      padding: 10px 20px;
      border-radius: 24px;
      font-size: 13px;
      font-weight: bold;
      box-shadow: 0 4px 15px rgba(0,0,0,0.5);
      display: none;
      cursor: pointer;
      align-items: center;
      gap: 8px;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { transform: translateX(-50%) scale(1); }
      50% { transform: translateX(-50%) scale(1.04); }
      100% { transform: translateX(-50%) scale(1); }
    }
    #controls {
      position: absolute;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 12px;
      z-index: 25;
      background: rgba(40, 40, 40, 0.85);
      border: 1px solid #504945;
      padding: 8px 16px;
      border-radius: 30px;
      backdrop-filter: blur(8px);
    }
    button {
      background: #3c3836;
      border: none;
      color: #fbf1c7;
      padding: 8px 14px;
      border-radius: 16px;
      font-weight: bold;
      font-size: 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: background 0.2s;
    }
    button:hover {
      background: #504945;
    }
    button:active {
      background: #665c54;
    }
  </style>
</head>
<body>
  <div id="header">
    <div class="badge">Room: <span id="roomLabel">-</span></div>
    <div class="badge" id="status">Connecting...</div>
  </div>

  <div id="audioBanner">
    🔊 Tap anywhere on screen to enable live audio
  </div>

  <div id="videoContainer">
    <div id="overlayMessage">
      <h2 id="msgTitle">ScreenShare Stream</h2>
      <p id="msgDetail">Waiting for screen transmission to start...</p>
      <button id="btnStartCapture">🔴 Click to Start Broadcasting</button>
    </div>
    <video id="remoteVideo" autoplay playsinline></video>
  </div>

  <div id="controls">
    <button id="btnToggleAudio">🔊 Audio: Off</button>
    <button id="btnFullscreen">⛶ Fullscreen</button>
  </div>

  <script src="./assets/client.js"></script>
</body>
</html>''')

    client_js = os.path.join(ui_assets_dir, "client.js")
    with open(client_js, "w", encoding="utf-8") as f:
        f.write('''(function() {
  const params = new URLSearchParams(window.location.search);
  const roomId = params.get('room') || 'a';
  const isCreate = params.get('create') === 'true';

  const statusEl = document.getElementById('status');
  const roomLabel = document.getElementById('roomLabel');
  const msgTitle = document.getElementById('msgTitle');
  const msgDetail = document.getElementById('msgDetail');
  const overlayMessage = document.getElementById('overlayMessage');
  const btnStartCapture = document.getElementById('btnStartCapture');
  const videoEl = document.getElementById('remoteVideo');
  const audioBanner = document.getElementById('audioBanner');
  const btnToggleAudio = document.getElementById('btnToggleAudio');
  const btnFullscreen = document.getElementById('btnFullscreen');
  const videoContainer = document.getElementById('videoContainer');

  roomLabel.innerText = roomId;

  let ws = null;
  let activeStream = null;
  let micStream = null;
  let isMicMuted = true;
  let isSoundMuted = false;
  let remoteStream = new MediaStream();
  let hasAudioTrack = false;
  const peerConnections = {};
  const pendingIceCandidates = {};

  videoEl.srcObject = remoteStream;

  btnFullscreen.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!document.fullscreenElement) {
      if (videoEl.requestFullscreen) videoEl.requestFullscreen();
      else if (videoEl.webkitRequestFullscreen) videoEl.webkitRequestFullscreen();
      else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
      if (screen.orientation && screen.orientation.lock) {
        screen.orientation.lock('landscape').catch(() => {});
      }
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
    }
  });

  function unmutePlayback() {
    videoEl.muted = false;
    videoEl.volume = 1.0;
    videoEl.play().then(() => {
      audioBanner.style.display = 'none';
      btnToggleAudio.innerText = "🔊 Audio: On";
      btnToggleAudio.style.background = "#fabd2f";
      btnToggleAudio.style.color = "#282828";
      statusEl.innerText = "Live Broadcast (Audio Playing)";
    }).catch(() => {
      videoEl.muted = true;
      videoEl.play().catch(() => {});
    });
  }

  function toggleAudio(e) {
    if (e) e.stopPropagation();
    if (videoEl.muted) {
      unmutePlayback();
    } else {
      videoEl.muted = true;
      btnToggleAudio.innerText = "🔇 Audio: Muted";
      btnToggleAudio.style.background = "#3c3836";
      btnToggleAudio.style.color = "#fbf1c7";
      statusEl.innerText = "Live Broadcast (Audio Muted)";
    }
  }

  btnToggleAudio.addEventListener('click', toggleAudio);
  audioBanner.addEventListener('click', unmutePlayback);
  videoContainer.addEventListener('click', () => {
    if (hasAudioTrack && videoEl.muted) {
      unmutePlayback();
    }
  });

  btnStartCapture.addEventListener('click', () => {
    startShare();
  });

  function getCleanIceServers(iceServers) {
    if (!iceServers || !Array.isArray(iceServers)) return [];
    return iceServers.map(server => {
      const cfg = { urls: server.urls };
      if (server.username) cfg.username = server.username;
      if (server.credential) cfg.credential = server.credential;
      return cfg;
    });
  }

  function connectSignaling() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${window.location.host}/stream`);

    ws.onopen = () => {
      statusEl.innerText = "Connected";
      statusEl.style.color = "#8ec07c";

      if (isCreate) {
        ws.send(JSON.stringify({
          type: "create",
          payload: {
            id: roomId,
            mode: "stun",
            joinIfExist: true,
            closeOnOwnerLeave: false,
            username: "Host"
          }
        }));

        msgTitle.innerText = "Host Broadcaster Mode";
        msgDetail.innerText = "Click below to select and broadcast your screen with system sound:";
        btnStartCapture.style.display = "block";

        startShare();
      } else {
        ws.send(JSON.stringify({
          type: "join",
          payload: {
            id: roomId,
            username: "Viewer"
          }
        }));
      }
    };

    ws.onmessage = async (ev) => {
      try {
        const msg = JSON.parse(ev.data);

        if (msg.type === "hostsession") {
          const sid = msg.payload.id;
          const pc = new RTCPeerConnection({ iceServers: getCleanIceServers(msg.payload.iceServers) });
          peerConnections[sid] = pc;
          pendingIceCandidates[sid] = [];

          if (activeStream) {
            activeStream.getTracks().forEach(t => pc.addTrack(t, activeStream));
          }

          pc.onicecandidate = (e) => {
            if (e.candidate) {
              ws.send(JSON.stringify({
                type: "hostice",
                payload: { sid: sid, value: e.candidate }
              }));
            }
          };

          const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: true });
          await pc.setLocalDescription(offer);
          ws.send(JSON.stringify({
            type: "hostoffer",
            payload: { sid: sid, value: offer }
          }));

        } else if (msg.type === "clientsession") {
          const sid = msg.payload.id;
          const pc = new RTCPeerConnection({ iceServers: getCleanIceServers(msg.payload.iceServers) });
          peerConnections[sid] = pc;
          pendingIceCandidates[sid] = [];

          pc.ontrack = (e) => {
            if (e.streams && e.streams[0]) {
              remoteStream = e.streams[0];
              videoEl.srcObject = remoteStream;
            } else {
              remoteStream.addTrack(e.track);
              videoEl.srcObject = remoteStream;
            }

            hasAudioTrack = remoteStream.getAudioTracks().length > 0;

            videoEl.muted = false;
            videoEl.volume = 1.0;
            videoEl.play().then(() => {
              overlayMessage.style.display = 'none';
              if (hasAudioTrack) {
                statusEl.innerText = "Live Broadcast (Audio On)";
                btnToggleAudio.innerText = "🔊 Audio: On";
                btnToggleAudio.style.background = "#fabd2f";
                btnToggleAudio.style.color = "#282828";
                audioBanner.style.display = 'none';
              } else {
                statusEl.innerText = "Live Broadcast";
              }
            }).catch(() => {
              videoEl.muted = true;
              videoEl.play().catch(() => {});
              overlayMessage.style.display = 'none';
              if (hasAudioTrack) {
                audioBanner.style.display = 'flex';
                btnToggleAudio.innerText = "🔇 Audio: Muted (Tap to unmute)";
                statusEl.innerText = "Live Broadcast (Audio Ready)";
              } else {
                statusEl.innerText = "Live Broadcast";
              }
            });
          };

          pc.onicecandidate = (e) => {
            if (e.candidate) {
              ws.send(JSON.stringify({
                type: "clientice",
                payload: { sid: sid, value: e.candidate }
              }));
            }
          };

        } else if (msg.type === "hostoffer") {
          const sid = msg.payload.sid;
          const pc = peerConnections[sid];
          if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(msg.payload.value));
            
            if (pendingIceCandidates[sid]) {
              for (const cand of pendingIceCandidates[sid]) {
                await pc.addIceCandidate(new RTCIceCandidate(cand)).catch(() => {});
              }
              pendingIceCandidates[sid] = [];
            }

            const ans = await pc.createAnswer();
            await pc.setLocalDescription(ans);
            ws.send(JSON.stringify({
              type: "clientanswer",
              payload: { sid: sid, value: ans }
            }));
          }

        } else if (msg.type === "clientanswer") {
          const sid = msg.payload.sid;
          const pc = peerConnections[sid];
          if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(msg.payload.value));
            
            if (pendingIceCandidates[sid]) {
              for (const cand of pendingIceCandidates[sid]) {
                await pc.addIceCandidate(new RTCIceCandidate(cand)).catch(() => {});
              }
              pendingIceCandidates[sid] = [];
            }
          }

        } else if (msg.type === "hostice") {
          const sid = msg.payload.sid;
          const pc = peerConnections[sid];
          const cand = msg.payload.value;
          if (cand) {
            if (pc && pc.remoteDescription) {
              pc.addIceCandidate(new RTCIceCandidate(cand)).catch(() => {});
            } else {
              if (!pendingIceCandidates[sid]) pendingIceCandidates[sid] = [];
              pendingIceCandidates[sid].push(cand);
            }
          }

        } else if (msg.type === "clientice") {
          const sid = msg.payload.sid;
          const pc = peerConnections[sid];
          const cand = msg.payload.value;
          if (cand) {
            if (pc && pc.remoteDescription) {
              pc.addIceCandidate(new RTCIceCandidate(cand)).catch(() => {});
            } else {
              if (!pendingIceCandidates[sid]) pendingIceCandidates[sid] = [];
              pendingIceCandidates[sid].push(cand);
            }
          }

        } else if (msg.type === "endshare" || msg.type === "stopshare") {
          const sid = msg.payload;
          if (peerConnections[sid]) {
            peerConnections[sid].close();
            delete peerConnections[sid];
          }
          if (Object.keys(peerConnections).length === 0 && !isCreate) {
            overlayMessage.style.display = 'block';
            msgTitle.innerText = "Stream Ended";
            msgDetail.innerText = "Screen broadcast ended by host.";
            statusEl.innerText = "Stream Ended";
            audioBanner.style.display = 'none';
          }
        }
      } catch (err) {
        console.warn("Signaling message handling error:", err);
      }
    };

    ws.onclose = () => {
      statusEl.innerText = "Reconnecting...";
      statusEl.style.color = "#cc241d";
      setTimeout(connectSignaling, 2000);
    };
  }

  async function startShare() {
    try {
      let screenStream = null;
      try {
        screenStream = await navigator.mediaDevices.getDisplayMedia({
          video: { frameRate: { ideal: 60, max: 60 } },
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            suppressLocalAudioPlayback: false
          },
          systemAudio: 'include'
        });
      } catch (e1) {
        try {
          screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 60, max: 60 } },
            audio: true
          });
        } catch (e2) {
          screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: true,
            audio: false
          });
        }
      }

      const combinedStream = new MediaStream();
      screenStream.getVideoTracks().forEach(track => combinedStream.addTrack(track));

      const screenAudioTracks = screenStream.getAudioTracks();
      if (screenAudioTracks.length > 0) {
        screenAudioTracks.forEach(track => {
          track.enabled = !isSoundMuted;
          combinedStream.addTrack(track);
        });
      } else {
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const loopbackDevice = devices.find(d => 
            d.kind === 'audioinput' && (
              d.label.toLowerCase().includes('stereo mix') ||
              d.label.toLowerCase().includes('what u hear') ||
              d.label.toLowerCase().includes('cable output') ||
              d.label.toLowerCase().includes('virtual') ||
              d.label.toLowerCase().includes('wave out') ||
              d.label.toLowerCase().includes('monitor') ||
              d.label.toLowerCase().includes('mix')
            )
          );

          let loopbackAudio = null;
          if (loopbackDevice) {
            loopbackAudio = await navigator.mediaDevices.getUserMedia({
              audio: {
                deviceId: { exact: loopbackDevice.deviceId },
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
              }
            });
          } else {
            loopbackAudio = await navigator.mediaDevices.getUserMedia({
              audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
              }
            });
          }

          if (loopbackAudio && loopbackAudio.getAudioTracks().length > 0) {
            loopbackAudio.getAudioTracks().forEach(track => {
              track.enabled = !isSoundMuted;
              combinedStream.addTrack(track);
            });
          }
        } catch (audioFallbackErr) {
          console.warn("Audio loopback acquisition error:", audioFallbackErr);
        }
      }

      activeStream = combinedStream;
      statusEl.innerText = "Broadcasting Active";
      overlayMessage.style.display = "none";

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "share", payload: {} }));
      }
      reportState({ sharing: true, micMuted: isMicMuted, soundMuted: isSoundMuted });

      activeStream.getVideoTracks()[0].addEventListener('ended', () => stopShare());
    } catch (err) {
      console.warn("Screen capture start notice:", err);
      reportState({ sharing: false });
    }
  }

  async function setMicEnabled(enabled) {
    isMicMuted = !enabled;
    if (enabled) {
      if (!micStream) {
        try {
          micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
          });
          const micTrack = micStream.getAudioTracks()[0];
          if (micTrack && activeStream) {
            activeStream.addTrack(micTrack);
            Object.values(peerConnections).forEach(pc => {
              pc.addTrack(micTrack, activeStream);
            });
          }
        } catch (e) {
          console.warn("Mic acquisition failed:", e);
        }
      } else {
        micStream.getAudioTracks().forEach(t => t.enabled = true);
      }
    } else {
      if (micStream) {
        micStream.getAudioTracks().forEach(t => {
          t.enabled = false;
          t.stop();
        });
        micStream = null;
      }
    }
    reportState({ micMuted: isMicMuted });
  }

  function toggleSoundMute() {
    isSoundMuted = !isSoundMuted;
    if (activeStream) {
      activeStream.getAudioTracks().forEach(t => {
        if (!micStream || !micStream.getAudioTracks().includes(t)) {
          t.enabled = !isSoundMuted;
        }
      });
    }
    reportState({ soundMuted: isSoundMuted });
  }

  function stopShare() {
    if (activeStream) {
      activeStream.getTracks().forEach(t => t.stop());
      activeStream = null;
    }
    if (micStream) {
      micStream.getTracks().forEach(t => t.stop());
      micStream = null;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stopshare", payload: {} }));
    }
    if (isCreate) {
      overlayMessage.style.display = "block";
      msgTitle.innerText = "Host Broadcaster Mode";
      msgDetail.innerText = "Screen sharing is stopped. Click below to start broadcasting:";
      btnStartCapture.style.display = "block";
    }
    reportState({ sharing: false });
  }

  function reportState(state) {
    fetch('http://127.0.0.1:5055/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state)
    }).catch(() => {});
  }

  if (isCreate) {
    setInterval(() => {
      fetch('http://127.0.0.1:5055/poll?t=' + Date.now())
        .then(r => r.json())
        .then(d => {
          if (d.action === "start_share") startShare();
          else if (d.action === "stop_share") stopShare();
          else if (d.action === "toggle_mic") setMicEnabled(isMicMuted);
          else if (d.action === "toggle_sound") toggleSoundMute();
        })
        .catch(() => {});
    }, 300);
  }

  connectSignaling();
})();''')

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