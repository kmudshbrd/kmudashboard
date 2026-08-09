#!/usr/bin/env python3
"""Local static server for site/ (dev only)."""
import os

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site"))

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


print("Serving site/ at http://localhost:8123")
ThreadingHTTPServer(("127.0.0.1", 8123), Handler).serve_forever()
