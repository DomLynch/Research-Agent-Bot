"""V1 entry point: CLI ('run') and stdlib HTTP dashboard ('dashboard').

Two subcommands:
  python -m agent.app run --topic ... --domain ... --criteria ...
  python -m agent.app dashboard --host 127.0.0.1 --port 8791

Dashboard is stdlib-only (http.server.ThreadingHTTPServer). Keeps the V0
cream/teal look. nginx terminates TLS upstream; this binds to 127.0.0.1 by
default and is reverse-proxied at research-agent.domlynch.com.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from agent.draft import run as run_draft
from agent.settings import load_settings

CSS = (
    ":root{--bg:#f3f0ea;--panel:#e4efef;--ink:#295b62;--muted:#5f8186;"
    "--line:#8db2b4;--error:#7c443c;--shadow:rgba(41,91,98,0.08)}"
    "*{box-sizing:border-box}"
    'body{margin:0;background:linear-gradient(180deg,#f7f3ed 0%,var(--bg) 100%);'
    'color:var(--ink);font:16px/1.5 "Avenir Next","Trebuchet MS",sans-serif}'
    ".wrap{max-width:980px;margin:40px auto;padding:0 20px 40px}"
    ".hero,.panel{background:var(--panel);border:1px solid var(--line);"
    "border-radius:18px;box-shadow:0 12px 30px var(--shadow)}"
    ".hero{padding:24px;margin-bottom:20px}"
    ".panel{padding:20px;margin-top:18px}"
    'h1,h2,h3{margin:0 0 12px;font-family:Georgia,"Times New Roman",serif}'
    "p{margin:0 0 10px;color:var(--muted)}"
    "form{display:grid;gap:14px}"
    ".grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}"
    "label{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
    "color:var(--muted);margin-bottom:6px}"
    "input,textarea{width:100%;border:1px solid var(--line);border-radius:12px;"
    "padding:12px 14px;background:#fbf8f3;color:var(--ink);font:inherit}"
    "textarea{min-height:120px;resize:vertical}"
    "button,.button{display:inline-block;border:0;border-radius:999px;"
    "padding:14px 20px;background:var(--ink);color:white;font:inherit;"
    "cursor:pointer;text-decoration:none}"
    ".button.secondary{background:#5f8186}"
    ".actions{margin:18px 0}"
    ".error{background:#fff1ed;color:var(--error);border-color:#d7a39a}"
    "pre{overflow:auto;background:#fbf8f3;padding:16px;border-radius:12px;"
    "border:1px solid var(--line);white-space:pre-wrap}"
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _render_page(*, form: dict[str, str], result: dict | None = None, error: str = "") -> str:
    error_block = (
        f'<section class="panel error"><strong>{_esc(error)}</strong></section>'
        if error else ""
    )
    result_block = ""
    if result:
        download_block = ""
        if result.get("markdown_file"):
            name = quote(Path(str(result["markdown_file"])).name, safe="")
            download_block = f'<a class="button secondary" href="/download?file={name}">Download .md</a>'
        md_block = f"<pre>{_esc(result.get('markdown', ''))}</pre>" if result.get("markdown") else ""
        approved = result.get("approved", False)
        approved_label = (
            '<span style="color:#2c6e3e">approved</span>' if approved
            else '<span style="color:var(--error)">REJECTED</span>'
        )
        failures = result.get("qa_failures") or []
        failures_block = ""
        if failures:
            items = "".join(
                f"<li><code>{_esc(f.get('code'))}</code>: {_esc(f.get('message'))}</li>"
                for f in failures[:10]
            )
            failures_block = f"<h3>QA failures</h3><ul>{items}</ul>"
        result_block = (
            '<section class="panel"><h2>Result</h2>'
            '<div class="grid">'
            f"<div><label>Approved</label><strong>{approved_label}</strong></div>"
            f"<div><label>Sources</label><strong>{_esc(result.get('n_sources', 0))} "
            f"({_esc(result.get('n_direct', 0))} direct)</strong></div>"
            f"<div><label>Attempts</label><strong>{_esc(result.get('attempts', 1))}</strong></div>"
            f"<div><label>Cost</label><strong>${_esc(round(float(result.get('estimated_cost_usd') or 0), 4))}</strong></div>"
            f"<div><label>Model</label><strong>{_esc(result.get('model', 'n/a'))}</strong></div>"
            f"<div><label>Elapsed</label><strong>{_esc(result.get('elapsed_sec', 0))}s</strong></div>"
            f"</div>{failures_block}"
            f'<div class="actions">{download_block}</div>'
            f"<h3>Draft</h3>{md_block}</section>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Research Agent</title><style>" + CSS + "</style></head>"
        "<body><div class='wrap'>"
        '<section class="hero"><h1>Research Agent</h1>'
        "<p>Type the topic, domain, and criteria. The agent searches, classifies "
        "the evidence, writes a deterministic-grounded draft, validates it, and "
        "shows the markdown.</p></section>"
        f"{error_block}"
        '<section class="panel"><form method="post" action="/run"><div class="grid">'
        f"<div><label>Topic</label><input name='topic' value='{_esc(form.get('topic', 'senolytics'))}' required></div>"
        f"<div><label>Domain</label><input name='domain' value='{_esc(form.get('domain', 'longevity older adults'))}' required></div>"
        "</div><div><label>Criteria / Scope</label>"
        f"<textarea name='criteria' placeholder='Example: human studies only, 2020+, safety signals.'>{_esc(form.get('criteria', ''))}</textarea>"
        "</div><button type='submit'>Run</button></form></section>"
        f"{result_block}</div></body></html>"
    )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/download":
            params = parse_qs(parsed.query, keep_blank_values=True)
            name = Path((params.get("file") or [""])[0]).name
            file_path = Path(load_settings().runs_dir) / name
            if not name or not file_path.exists():
                self.send_error(404)
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass
            return
        self._send(_render_page(form={}).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
        result = run_draft(
            topic=form.get("topic", ""),
            domain=form.get("domain", ""),
            criteria=form.get("criteria", ""),
        )
        error = str(result.get("error", "")) if result.get("error") else ""
        self._send(_render_page(form=form, result=result, error=error).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        return  # suppress access logs

    def _send(self, data: bytes, *, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return


def cli_run(args: argparse.Namespace) -> int:
    result = run_draft(topic=args.topic, domain=args.domain, criteria=args.criteria)
    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result.get("markdown") or f"REJECTED: {[f['code'] for f in result.get('qa_failures', [])]}")
    return 0


def dashboard_main(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Research Agent V1 dashboard at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.app", description="Research Agent V1")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a single topic/domain/criteria")
    r.add_argument("--topic", required=True)
    r.add_argument("--domain", required=True)
    r.add_argument("--criteria", default="")
    r.add_argument("--json", action="store_true", help="print full JSON result")
    d = sub.add_parser("dashboard", help="serve the HTTP dashboard")
    s = load_settings()
    d.add_argument("--host", default=s.dashboard_host)
    d.add_argument("--port", type=int, default=s.dashboard_port)
    args = parser.parse_args(argv)
    return cli_run(args) if args.cmd == "run" else dashboard_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
