#################### START OF FILE: ui_failsafe.py ####################

import os

def write_failsafe_client(ui_dir):
    """Generates a resilient fallback application inside ui/build with mobile audio context unlocking and candidate exchange."""
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
      user-select: none;
      -webkit-user-select: none;
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
      top: 65px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 30;
      background: #fabd2f;
      color: #282828;
      padding: 12px 24px;
      border-radius: 26px;
      font-size: 14px;
      font-weight: bold;
      box-shadow: 0 6px 20px rgba(0,0,0,0.6);
      display: none;
      cursor: pointer;
      align-items: center;
      gap: 10px;
      text-align: center;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { transform: translateX(-50%) scale(1); }
      50% { transform: translateX(-50%) scale(1.03); }
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
    🔊 Tap to play live audio (turn off Silent Mode)
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
    <button id="btnToggleAudio">🔊 Sound: Playing</button>
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
  const controlsEl = document.getElementById('controls');
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
  let audioContextUnlocked = false;
  const peerConnections = {};
  const pendingIceCandidates = {};

  if (isCreate) {
    controlsEl.style.display = 'none';
    audioBanner.style.display = 'none';
  } else {
    videoEl.srcObject = remoteStream;
  }

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

  function unlockAudioEngine() {
    if (audioContextUnlocked || isCreate) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        if (!window.__ssAudioContext) {
          window.__ssAudioContext = new AudioCtx();
        }
        if (window.__ssAudioContext.state === 'suspended') {
          window.__ssAudioContext.resume();
        }
      }
      audioContextUnlocked = true;
    } catch (_) {}
  }

  function unmutePlayback(e) {
    if (isCreate) return;
    if (e) {
      if (typeof e.stopPropagation === 'function') e.stopPropagation();
    }

    unlockAudioEngine();
    audioBanner.style.display = 'none';

    videoEl.pause();
    videoEl.muted = false;
    videoEl.playsInline = true;
    videoEl.volume = 1.0;
    
    // iOS Safari workaround
    if (remoteStream && videoEl.srcObject === remoteStream) {
      videoEl.srcObject = null;
      videoEl.srcObject = remoteStream;
    }

    btnToggleAudio.innerText = "🔊 Sound: Playing";
    btnToggleAudio.style.background = "#fabd2f";
    btnToggleAudio.style.color = "#282828";
    statusEl.innerText = "Live Broadcast (Sound Active)";

    videoEl.play().catch(() => {});
  }

  function toggleAudio(e) {
    if (e) e.stopPropagation();
    if (isCreate) return;

    if (videoEl.muted) {
      unmutePlayback();
    } else {
      videoEl.muted = true;
      btnToggleAudio.innerText = "🔇 Sound: Muted";
      btnToggleAudio.style.background = "#3c3836";
      btnToggleAudio.style.color = "#fbf1c7";
      statusEl.innerText = "Live Broadcast (Sound Muted)";
    }
  }

  btnToggleAudio.addEventListener('click', toggleAudio);
  audioBanner.addEventListener('click', unmutePlayback);
  audioBanner.addEventListener('touchstart', unmutePlayback, { passive: true });
  videoContainer.addEventListener('click', unmutePlayback);
  videoContainer.addEventListener('touchstart', unmutePlayback, { passive: true });

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

  function updateHostBadge() {
    if (!isCreate) return;
    if (activeStream) {
      let soundText = isSoundMuted ? "Sound Off" : "Sound On";
      let micText = isMicMuted ? "Mic Off" : "Mic On";
      statusEl.innerText = `Broadcasting (${soundText}, ${micText})`;
      statusEl.style.color = "#8ec07c";
    } else {
      statusEl.innerText = "Broadcasting Standby";
      statusEl.style.color = "#fabd2f";
    }
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
        msgDetail.innerText = "Click below to start broadcasting screen & computer sound:";
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

            // Attempt unmuted play first; if autoplay blocked, display tap prompt banner
            videoEl.muted = false;
            videoEl.volume = 1.0;
            videoEl.play().then(() => {
              overlayMessage.style.display = 'none';
              audioBanner.style.display = 'none';
              btnToggleAudio.innerText = "🔊 Sound: Playing";
              btnToggleAudio.style.background = "#fabd2f";
              btnToggleAudio.style.color = "#282828";
              statusEl.innerText = "Live Broadcast (Sound Active)";
            }).catch(() => {
              videoEl.muted = true;
              videoEl.play().catch(() => {});
              overlayMessage.style.display = 'none';
              audioBanner.style.display = 'flex';
              btnToggleAudio.innerText = "🔇 Sound: Muted (Tap to hear)";
              statusEl.innerText = "Live Broadcast (Tap for Sound)";
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
          video: { frameRate: { ideal: 60, max: 60 }, displaySurface: "monitor" },
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
            suppressLocalAudioPlayback: false
          },
          systemAudio: 'include',
          selfBrowserSurface: 'exclude',
          surfaceSwitching: 'include'
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

          let audioStream = null;
          if (loopbackDevice) {
            audioStream = await navigator.mediaDevices.getUserMedia({
              audio: {
                deviceId: { exact: loopbackDevice.deviceId },
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
              }
            });
          } else {
            audioStream = await navigator.mediaDevices.getUserMedia({
              audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
              }
            });
          }

          if (audioStream && audioStream.getAudioTracks().length > 0) {
            audioStream.getAudioTracks().forEach(track => {
              track.enabled = !isSoundMuted;
              combinedStream.addTrack(track);
            });
          }
        } catch (audioFallbackErr) {
          console.warn("Audio loopback acquisition error:", audioFallbackErr);
        }
      }

      activeStream = combinedStream;
      overlayMessage.style.display = "none";
      updateHostBadge();

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
    updateHostBadge();
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
    updateHostBadge();
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
    updateHostBadge();
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