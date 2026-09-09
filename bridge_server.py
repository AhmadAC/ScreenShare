import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from PySide6.QtCore import QObject, Signal
from system_util import set_physical_mics_muted

PORT = 5055

class CommSignals(QObject):
    state_updated = Signal(dict)

comm = CommSignals()

app_state = {
    "sharing": False,
    "paused": False,
    "micMuted": False,
    "soundMuted": False
}
pending_action = None

def get_app_state():
    return app_state

def update_app_state(new_state):
    app_state.update(new_state)

def get_pending_action():
    global pending_action
    action = pending_action
    pending_action = None
    return action

def set_pending_action(action):
    global pending_action
    pending_action = action

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, *')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()

        clean_path = self.path.split('?')[0].rstrip('/')
        if clean_path in ('/poll', 'poll'):
            action = get_pending_action()
            if action:
                self.wfile.write(json.dumps({"action": action}).encode('utf-8'))
            else:
                self.wfile.write(b'{"action": "none"}')
        elif clean_path in ('/state', 'state'):
            self.wfile.write(json.dumps(get_app_state()).encode('utf-8'))
        else:
            self.wfile.write(b'{"status": "ok"}')

    def do_POST(self):
        clean_path = self.path.split('?')[0].rstrip('/')
        if clean_path in ('/state', 'state'):
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                try:
                    data = json.loads(post_data.decode('utf-8'))
                    update_app_state(data)
                    comm.state_updated.emit(get_app_state())
                    if "micMuted" in data:
                        set_physical_mics_muted(data["micMuted"])
                except Exception:
                    pass
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

class ThreadingHTTPServer(ThreadingTCPServer, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_http_server(port=PORT):
    server = ThreadingHTTPServer(('127.0.0.1', port), BridgeHandler)
    server.serve_forever()