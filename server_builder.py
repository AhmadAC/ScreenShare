# server_builder.py
"""
Facade for the server builder module.
Re-exports functions to preserve the original API for control_server.py.
"""
from process_util import start_screenshare_server, wait_for_server
from browser_launcher import launch_hidden_browser

__all__ = [
    "start_screenshare_server",
    "wait_for_server",
    "launch_hidden_browser"
]