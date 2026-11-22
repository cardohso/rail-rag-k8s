"""Throwaway stand-in for the api, used only to test the chart before the real image exists (step 4).

Serves the same probe paths. /ask sleeps like the fake generator. Waits STUB_STARTUP_SECONDS
before it reports started, so the startup probe has something to wait for. No dependencies.
"""

import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.monotonic()
STARTUP = float(os.environ.get("STUB_STARTUP_SECONDS", "5"))
ready = True


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"ok"):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        started = time.monotonic() - START >= STARTUP
        code = {
            "/livez": 200,
            "/startupz": 200 if started else 503,
            "/readyz": 200 if started and ready else 503,
            "/metrics": 200,
        }.get(self.path, 404)
        self._send(code)

    def do_POST(self):
        time.sleep(0.3)
        self._send(200, json.dumps({"answer": "stub"}).encode())

    def log_message(self, *args):
        pass


def main():
    global ready
    server = ThreadingHTTPServer(("0.0.0.0", 7860), Handler)

    def stop(*_):
        global ready
        ready = False
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGTERM, stop)
    server.serve_forever()


main()
