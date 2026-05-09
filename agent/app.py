"""Deploy-safe live status service for the research synthesis engine.

The deployed systemd unit runs `python -m agent.app dashboard ...`. This module
keeps that unit healthy and visibly live while synthesis work is executed
through scripts and audited run bundles rather than a public interactive API.
"""
from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LIVE_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<title>Research Agent - live</title>"
    "<style>body{font-family:Georgia,serif;max-width:640px;margin:80px auto;"
    "padding:0 20px;color:#295b62;line-height:1.5}"
    "h1{font-weight:normal}code{background:#f0ebe2;padding:2px 6px;"
    "border-radius:4px;font-size:.9em}</style></head><body>"
    "<h1>Research Agent service live</h1>"
    "<p>The synthesis engine is deployed and healthy. Papers are generated "
    "through audited run bundles, not this public status endpoint.</p>"
    "<p>Current source of truth: claim graphs, manifests, verdict JSON, and "
    "certification artifacts. Markdown is downstream rendering.</p>"
    "</body></html>"
)
_PAUSE_HTML = _LIVE_HTML  # Back-compat for older tests/imports.


class _LiveHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = _LIVE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def log_message(self, format: str, *args: object) -> None:
        return  # suppress access logs


def _dashboard(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), _LiveHandler)
    print(f"Research Agent live status on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _run(_args: argparse.Namespace) -> int:
    print(
        "ERROR: agent.app run is not the active synthesis entrypoint.\n"
        "       Use scripts/run_v06_synthesis.py or scripts/synthesize.py "
        "to generate audited papers.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent.app", description="Research Agent live status service",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="(unavailable during rebuild)")
    r.add_argument("--topic")
    r.add_argument("--domain")
    r.add_argument("--criteria", default="")
    r.add_argument("--json", action="store_true")
    d = sub.add_parser("dashboard", help="serve the live status HTTP page")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8791)
    args = parser.parse_args(argv)
    return _run(args) if args.cmd == "run" else _dashboard(args)


if __name__ == "__main__":
    raise SystemExit(main())
