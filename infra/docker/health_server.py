"""Temporary P1-02 container health server; replaced by the FastAPI/worker entrypoints later."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/health/live", "/health/ready"}:
            self.send_response(404)
            self.end_headers()
            return

        payload = json.dumps({"status": "ok", "service": "classvoice-placeholder"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check")
    args = parser.parse_args()

    if args.check:
        try:
            with urlopen(args.check, timeout=2) as response:  # noqa: S310
                if response.status != 200:
                    raise RuntimeError(f"health returned {response.status}")
        except Exception as exc:  # noqa: BLE001
            print(f"health check failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    ThreadingHTTPServer(("0.0.0.0", args.port), HealthHandler).serve_forever()


if __name__ == "__main__":
    main()
