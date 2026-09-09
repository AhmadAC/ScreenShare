import os
import sys
import socket
import shutil
import datetime
import subprocess

EXECUTION_DIR = os.environ.get("OWD", os.getcwd())
LOG_FILE_PATH = os.path.join(EXECUTION_DIR, "ScreenShare-host.log")
LINK_FILE_PATH = os.path.join(EXECUTION_DIR, "link.txt")

original_default_source = None
remap_module_id = None
active_audio_source_name = None

def get_base_dir():
    """Returns the base directory whether running as script or frozen PyInstaller binary."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def log(msg):
    """Outputs timestamped message to stdout and appends to ScreenShare-host.log."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception as e:
        print(f"Failed to write to log file {LOG_FILE_PATH}: {e}")

def write_link_file(url):
    """Writes the shareable viewer URL to link.txt in the execution directory."""
    try:
        with open(LINK_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(url.strip() + "\n")
        log(f"Viewer link written to: {LINK_FILE_PATH}")
    except Exception as e:
        log(f"Failed to write link.txt: {e}")

def get_clean_host_env():
    """Strips AppImage and PyInstaller specific variables so host processes don't crash."""
    env = os.environ.copy()
    if sys.platform.startswith("win"):
        return env

    vars_to_remove = [
        "LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONPATH", "PYTHONHOME",
        "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "GSETTINGS_SCHEMA_DIR",
        "GTK_PATH", "GTK_MODULES", "GTK_EXE_PREFIX", "FONTCONFIG_PATH",
        "FONTCONFIG_FILE", "APPIMAGE", "APPDIR", "ARGV0"
    ]
    for var in vars_to_remove:
        env.pop(var, None)

    current_path = env.get("PATH", "")
    paths = [p for p in current_path.split(":") if not p.startswith("/tmp/.mount_")]
    extra_paths = [
        "/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin", "/sbin",
        "/snap/bin", "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
        os.path.expanduser("~/.local/bin"), os.path.expanduser("~/bin"),
    ]
    for ep in extra_paths:
        if ep not in paths:
            paths.append(ep)
    env["PATH"] = ":".join(paths)

    xdg_data = env.get("XDG_DATA_DIRS", "")
    if xdg_data:
        cleaned_dirs = [d for d in xdg_data.split(":") if not d.startswith("/tmp/.mount_")]
        standard_xdg = [
            os.path.expanduser("~/.local/share/flatpak/exports/share"),
            "/var/lib/flatpak/exports/share", "/usr/local/share", "/usr/share"
        ]
        for s in standard_xdg:
            if s not in cleaned_dirs:
                cleaned_dirs.append(s)
        env["XDG_DATA_DIRS"] = ":".join(cleaned_dirs)
    else:
        env["XDG_DATA_DIRS"] = f"{os.path.expanduser('~/.local/share/flatpak/exports/share')}:/var/lib/flatpak/exports/share:/usr/local/share:/usr/share"

    return env

def detect_lan_ip():
    """Automatically detects the real Wi-Fi / Ethernet IPv4 address, filtering out virtual/TUN subnets."""
    if sys.platform.startswith("linux"):
        clean_env = get_clean_host_env()
        try:
            res = subprocess.run(["ip", "-4", "-o", "addr", "show"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
            candidates = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    ifname = parts[1]
                    ip = parts[3].split("/")[0]
                    if ip.startswith("127.") or ip.startswith("198.18.") or ip.startswith("169.254."):
                        continue
                    if any(ifname.startswith(p) for p in ["lo", "docker", "veth", "br-", "tun", "tap", "wg", "tailscale"]):
                        continue
                    candidates.append((ifname, ip))

            for ifname, ip in candidates:
                if ifname.startswith("wl") or ifname.startswith("eth") or ifname.startswith("en"):
                    return ip
            if candidates:
                return candidates[0][1]
        except Exception:
            pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("198.18.") and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"

def kill_port_owners():
    """Terminates any stale processes using ScreenShare/Control ports on Linux and Windows."""
    ports = [5050, 5055, 3478]
    if sys.platform.startswith("win"):
        current_pid = os.getpid()
        for port in ports:
            try:
                res = subprocess.run(
                    ["netstat", "-ano", "-p", "tcp"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True
                )
                for line in res.stdout.splitlines():
                    if f":{port} " in line and "LISTENING" in line:
                        parts = line.strip().split()
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            target_pid = int(pid_str)
                            if target_pid != current_pid and target_pid != 0:
                                subprocess.run(["taskkill", "/F", "/PID", str(target_pid)],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        return

    clean_env = get_clean_host_env()
    ports_str = ["5050/tcp", "5055/tcp", "3478/tcp", "3478/udp"]
    for port in ports_str:
        subprocess.run(["fuser", "-k", port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)

def setup_windows_audio():
    """Ensures Stereo Mix or virtual audio loopback endpoints are enabled on Windows."""
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        base_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as cap_key:
                num_subkeys = winreg.QueryInfoKey(cap_key)[0]
                for i in range(num_subkeys):
                    subkey_name = winreg.EnumKey(cap_key, i)
                    dev_path = f"{base_path}\\{subkey_name}"
                    prop_path = f"{dev_path}\\Properties"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prop_path, 0, winreg.KEY_READ) as prop_key:
                            num_vals = winreg.QueryInfoKey(prop_key)[1]
                            is_loopback = False
                            for j in range(num_vals):
                                _, val, _ = winreg.EnumValue(prop_key, j)
                                if isinstance(val, str) and any(s in val.lower() for s in ["stereo mix", "what u hear", "wave out", "stereo mixer", "cable output"]):
                                    is_loopback = True
                                    break
                            
                            if is_loopback:
                                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dev_path, 0, winreg.KEY_SET_VALUE) as dev_key:
                                    winreg.SetValueEx(dev_key, "DeviceState", 0, winreg.REG_DWORD, 1)
                                log(f"Audio setup: Enabled loopback endpoint '{subkey_name}' in Windows registry.")
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception as e:
        log(f"Notice during Windows audio setup: {e}")

def run_audio_cmd(args):
    """Executes pactl commands directly on Linux."""
    if not sys.platform.startswith("linux"):
        return
    clean_env = get_clean_host_env()
    try:
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
    except Exception:
        pass

def get_physical_mic_sources():
    """Returns a list of all physical microphone source names on Linux."""
    if not sys.platform.startswith("linux"):
        return []
    clean_env = get_clean_host_env()
    try:
        res = subprocess.run(["pactl", "list", "short", "sources"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        sources = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                sname = parts[1]
                if not sname.endswith(".monitor") and sname != "ComputerSound":
                    sources.append(sname)
        return sources
    except Exception:
        return []

def set_physical_mics_muted(muted: bool):
    """Mutes or unmutes all physical microphones at the OS level on Windows and Linux."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)
                ]

            def make_guid(d1, d2, d3, d4_bytes):
                g = GUID()
                g.Data1 = d1
                g.Data2 = d2
                g.Data3 = d3
                for i in range(8):
                    g.Data4[i] = d4_bytes[i]
                return g

            CLSID_MMDeviceEnumerator = make_guid(0xBCDE0395, 0xE52F, 0x467C, [0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E])
            IID_IMMDeviceEnumerator = make_guid(0xA95664D2, 0x9614, 0x4F35, [0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6])
            IID_IAudioEndpointVolume = make_guid(0x5CDF2C82, 0x841E, 0x4546, [0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22, 0x9A])

            pEnumerator = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_MMDeviceEnumerator),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(IID_IMMDeviceEnumerator),
                ctypes.byref(pEnumerator)
            )

            if hr == 0 and pEnumerator.value:
                vtable_enum = ctypes.cast(pEnumerator, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

                EnumAudioEndpoints_func = ctypes.WINFUNCTYPE(
                    wintypes.LONG, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
                )(vtable_enum[3])

                pCollection = ctypes.c_void_p()
                hr_coll = EnumAudioEndpoints_func(pEnumerator, 1, 1, ctypes.byref(pCollection))

                if hr_coll == 0 and pCollection.value:
                    vtable_coll = ctypes.cast(pCollection, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                    GetCount_func = ctypes.WINFUNCTYPE(wintypes.LONG, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT))(vtable_coll[3])
                    Item_func = ctypes.WINFUNCTYPE(wintypes.LONG, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(vtable_coll[4])

                    count = wintypes.UINT(0)
                    GetCount_func(pCollection, ctypes.byref(count))

                    for i in range(count.value):
                        pDevice = ctypes.c_void_p()
                        if Item_func(pCollection, i, ctypes.byref(pDevice)) == 0 and pDevice.value:
                            vtable_dev = ctypes.cast(pDevice, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                            Activate_func = ctypes.WINFUNCTYPE(
                                wintypes.LONG, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
                            )(vtable_dev[3])

                            pEndpointVol = ctypes.c_void_p()
                            if Activate_func(pDevice, ctypes.byref(IID_IAudioEndpointVolume), 23, None, ctypes.byref(pEndpointVol)) == 0 and pEndpointVol.value:
                                vtable_vol = ctypes.cast(pEndpointVol, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                                SetMute_func = ctypes.WINFUNCTYPE(
                                    wintypes.LONG, ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p
                                )(vtable_vol[14])

                                SetMute_func(pEndpointVol, 1 if muted else 0, None)

                                Release_vol = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable_vol[2])
                                Release_vol(pEndpointVol)

                            Release_dev = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable_dev[2])
                            Release_dev(pDevice)

                    Release_coll = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable_coll[2])
                    Release_coll(pCollection)

                Release_enum = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable_enum[2])
                Release_enum(pEnumerator)
        except Exception as e:
            log(f"Notice: Failed to set Windows mic mute: {e}")
        return

    # Linux (PulseAudio / PipeWire)
    mute_val = "1" if muted else "0"
    for s in get_physical_mic_sources():
        run_audio_cmd(["pactl", "set-source-mute", s, mute_val])
    if original_default_source and not original_default_source.endswith(".monitor") and original_default_source != "ComputerSound":
        run_audio_cmd(["pactl", "set-source-mute", original_default_source, mute_val])

def setup_pipewire_audio():
    """Sets up virtual audio source (Computer Sound) monitoring on Linux."""
    if not sys.platform.startswith("linux"):
        return
    global original_default_source, remap_module_id, active_audio_source_name
    clean_env = get_clean_host_env()
    try:
        res_src = subprocess.run(["pactl", "get-default-source"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        original_default_source = res_src.stdout.strip()

        res_sink = subprocess.run(["pactl", "get-default-sink"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)
        default_sink = res_sink.stdout.strip()
        if not default_sink:
            return

        monitor_source = f"{default_sink}.monitor"
        load_res = subprocess.run([
            "pactl", "load-module", "module-remap-source",
            "source_name=ComputerSound",
            f"master={monitor_source}",
            "source_properties=device.description=\"Computer Sound\""
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env)

        if load_res.returncode == 0 and load_res.stdout.strip().isdigit():
            remap_module_id = load_res.stdout.strip()
            active_audio_source_name = "ComputerSound"
            run_audio_cmd(["pactl", "set-default-source", "ComputerSound"])
            run_audio_cmd(["pactl", "set-source-mute", "ComputerSound", "0"])
            run_audio_cmd(["pactl", "set-source-volume", "ComputerSound", "100%"])
            log("Audio setup: Loaded module-remap-source ('Computer Sound')")
        else:
            active_audio_source_name = monitor_source
            run_audio_cmd(["pactl", "set-default-source", monitor_source])
            run_audio_cmd(["pactl", "set-source-mute", monitor_source, "0"])
            log(f"Audio setup: Default source fallback to {monitor_source}")
    except Exception as e:
        log(f"Warning: Audio setup encountered: {e}")

def cleanup_audio():
    """Restores the original audio default source and unmutes physical microphones."""
    set_physical_mics_muted(False)

    if not sys.platform.startswith("linux"):
        return

    global original_default_source, remap_module_id

    if remap_module_id:
        run_audio_cmd(["pactl", "unload-module", remap_module_id])
    else:
        run_audio_cmd(["pactl", "unload-module", "module-remap-source"])

    if original_default_source:
        run_audio_cmd(["pactl", "set-default-source", original_default_source])

def get_active_audio_source():
    """Returns the name of the currently active virtual audio source."""
    return active_audio_source_name or "ComputerSound"

def sync_audio_volume():
    """Continuously syncs the default sink volume to Computer Sound on Linux."""
    if not sys.platform.startswith("linux"):
        return
    clean_env = get_clean_host_env()
    try:
        res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], stdout=subprocess.PIPE, text=True, env=clean_env)
        if res.stdout:
            parts = res.stdout.split('/')
            if len(parts) > 1:
                vol_str = parts[1].strip()
                source = get_active_audio_source()
                subprocess.run(["pactl", "set-source-volume", source, vol_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)

        proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True, env=clean_env)
        for line in iter(proc.stdout.readline, ''):
            if "change" in line and "sink" in line:
                res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], stdout=subprocess.PIPE, text=True, env=clean_env)
                if res.stdout:
                    parts = res.stdout.split('/')
                    if len(parts) > 1:
                        vol_str = parts[1].strip()
                        source = get_active_audio_source()
                        subprocess.run(["pactl", "set-source-volume", source, vol_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
    except Exception:
        pass