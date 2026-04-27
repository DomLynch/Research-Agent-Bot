"""Deploy-safe placeholder for Proof 001 rebuild window.

The original app.py (CLI + dashboard built on the LLM-coupled draft pipeline) was
archived to agent_archived/proof001/agent/app.py during Day 0 of the Proof 001
rebuild on 2026-04-27. The new app.py + mcp_server.py land on Day 5 per
docs/DESIGN-001.md.

This module exists ONLY so that the deployed systemd unit
(deploy/research-agent-bot.service runs `python -m agent.app dashboard ...`)
can start cleanly during the rebuild window. It serves a static "service paused"
page on the same port the dashboard used; the CLI subcommands return a clear
exit message rather than an ImportError chain.

Replace this stub on Day 5 with the claim-graph-driven app.
"""
from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PAUSE_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<title>Research Agent — paused</title>"
    "<style>body{font-family:Georgia,serif;max-width:640px;margin:80px auto;"
    "padding:0 20px;color:#295b62;line-height:1.5}"
    "h1{font-weight:normal}code{background:#f0ebe2;padding:2px 6px;"
    "border-radius:4px;font-size:.9em}</style></head><body>"
    "<h1>Service paused — Proof 001 rebuild in progress</h1>"
    "<p>The Research Agent runtime is between architectures. The V1.1 "
    "LLM-coupled pipeline was archived on 2026-04-27 (tag <code>v1.1-final</code>); "
    "the Proof 001 claim-court pipeline is being built per "
    "<code>docs/DESIGN-001.md</code>.</p>"
    "<p>This page is served by a deploy-safe stub so the systemd unit stays "
    "healthy during the rebuild window. The new dashboard ships on Day 5.</p>"
    "</body></html>"
)


class _PauseHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = _PAUSE_HTML.encode("utf-8")
        self.send_response(503)  # Service Unavailable — honest signal
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "86400")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def log_message(self, format: str, *args: object) -> None:
        return  # suppress access logs


def _dashboard(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), _PauseHandler)
    print(f"Research Agent paused-stub on http://{args.host}:{args.port} (Proof 001 rebuild)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _run(_args: argparse.Namespace) -> int:
    print(
        "ERROR: agent.app run is unavailable during the Proof 001 rebuild.\n"
        "       The V1.1 CLI was archived on 2026-04-27 (tag v1.1-final).\n"
        "       The new claim-graph-driven CLI ships on Day 5 per DESIGN-001.md.\n"
        "       To execute V1.1: git checkout v1.1-final && pip install -e .",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.app", description="Research Agent (Proof 001 rebuild stub)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="(unavailable during rebuild)")
    r.add_argument("--topic")
    r.add_argument("--domain")
    r.add_argument("--criteria", default="")
    r.add_argument("--json", action="store_true")
    d = sub.add_parser("dashboard", help="serve the paused-stub HTTP page")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8791)
    args = parser.parse_args(argv)
    return _run(args) if args.cmd == "run" else _dashboard(args)


if __name__ == "__main__":
    raise SystemExit(main())
