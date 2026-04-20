from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from agent.cli import run_agent

CSS = (
    ":root{--bg:#f3f0ea;--panel:#e4efef;--ink:#295b62;--muted:#5f8186;--line:#8db2b4;--error:#7c443c;--shadow:rgba(41,91,98,0.08)}"
    "*{box-sizing:border-box}"
    'body{margin:0;background:linear-gradient(180deg,#f7f3ed 0%,var(--bg) 100%);color:var(--ink);font:16px/1.5 "Avenir Next","Trebuchet MS",sans-serif}'
    ".wrap{max-width:980px;margin:40px auto;padding:0 20px 40px}"
    ".hero,.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:0 12px 30px var(--shadow)}"
    ".hero{padding:24px;margin-bottom:20px}"
    ".panel{padding:20px;margin-top:18px}"
    'h1,h2,h3{margin:0 0 12px;font-family:Georgia,"Times New Roman",serif}'
    "p{margin:0 0 10px;color:var(--muted)}"
    "form{display:grid;gap:14px}"
    ".grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}"
    "label{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}"
    "input,textarea{width:100%;border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#fbf8f3;color:var(--ink);font:inherit}"
    "textarea{min-height:120px;resize:vertical}"
    "button,.button{display:inline-block;border:0;border-radius:999px;padding:14px 20px;background:var(--ink);color:white;font:inherit;cursor:pointer;text-decoration:none}"
    ".button.secondary{background:#5f8186}"
    ".actions{margin:18px 0}"
    ".error{background:#fff1ed;color:var(--error);border-color:#d7a39a}"
    "pre{overflow:auto;background:#fbf8f3;padding:16px;border-radius:12px;border:1px solid var(--line);white-space:pre-wrap}"
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _render_page(*, form: dict[str, str], result: dict | None = None, error: str = "") -> str:
    error_block = f'<section class="panel error"><strong>{_esc(error)}</strong></section>' if error else ""
    result_block = ""
    if result:
        download_block = ""
        if result.get("markdown_file"):
            download_name = quote(str(result["markdown_file"]), safe="")
            download_block = f'<a class="button secondary" href="/download?file={download_name}">Download .md</a>'
        md = result.get("markdown", "")
        md_block = f"<pre>{_esc(md)}</pre>" if md else ""
        scope_block = ""
        if result.get("scope_signals"):
            scope_block = f"<p>Scope signals: {_esc(', '.join(result['scope_signals']))}</p>"
        sub_block = ""
        sub = result.get("submission", {})
        if sub.get("duplicate"):
            sub_block = (
                f"<div><label>Submission</label><strong>skipped (duplicate)</strong></div>"
                f"<div><label>Previous ID</label><strong>{_esc(str(sub.get('previous_submission_id', '?'))[:8])}…</strong></div>"
            )
        else:
            sub_id = sub.get("submission", {}).get("id")
            decision = sub.get("decision", {})
            if sub_id:
                dec_status = decision.get("status", "pending")
                dec_verdict = decision.get("decision", "—")
                gates = decision.get("gate_failures", [])
                gate_str = "; ".join(g["reason"] for g in gates) if gates else "all passed"
                pub_str = ""
                if sub.get("publication_id"):
                    pub_str = f"<div><label>Publication</label><strong>{_esc(str(sub['publication_id'])[:8])}…</strong></div>"
                sub_block = (
                    f"<div><label>Submission</label><strong>{_esc(sub_id[:8])}…</strong></div>"
                    f"<div><label>Decision</label><strong>{_esc(dec_verdict)} ({_esc(dec_status)})</strong></div>"
                    f"<div><label>Intake Gates</label><strong>{_esc(gate_str)}</strong></div>"
                    f"{pub_str}"
                )
        result_block = (
            '<section class="panel"><h2>Result</h2>'
            '<div class="grid">'
            f"<div><label>Model</label><strong>{_esc(result.get('model', 'n/a'))}</strong></div>"
            f"<div><label>Evidence Kept</label><strong>{_esc(result.get('evidence_selected', 0))}</strong></div>"
            f"<div><label>Retrieved / Errors</label><strong>{_esc(result.get('evidence_retrieved', 0))} / {_esc(len(result.get('source_errors', [])))}</strong></div>"
            f"<div><label>Cost</label><strong>${_esc(result.get('estimated_cost_usd', 0.0))}</strong></div>"
            f"{sub_block}"
            f"</div>{scope_block}"
            f'<div class="actions">{download_block}</div>'
            f"<h3>Draft</h3>{md_block}</section>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Research Agent</title><style>" + CSS + "</style></head><body><div class='wrap'>"
        '<section class="hero"><h1>Research Agent</h1>'
        "<p>Type the topic, domain, and criteria. The agent searches, writes the draft, shows it below, and gives you a markdown download.</p>"
        f"</section>{error_block}"
        '<section class="panel"><form method="post" action="/run">'
        '<div class="grid">'
        f"<div><label>Topic</label><input name='topic' value='{_esc(form.get('topic', 'senolytics and healthspan'))}' required></div>"
        f"<div><label>Domain</label><input name='domain' value='{_esc(form.get('domain', 'longevity'))}' required></div>"
        "</div><div><label>Criteria / Scope</label>"
        f"<textarea name='criteria' placeholder='Example: human studies only, 2020+, safety signals, avoid animal-only evidence.'>{_esc(form.get('criteria', ''))}</textarea>"
        "</div><button type='submit'>Run</button></form></section>"
        f"{result_block}</div></body></html>"
    )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/download":
            params = parse_qs(parsed.query, keep_blank_values=True)
            name = Path((params.get("file") or [""])[0]).name
            file_path = Path("runs") / name
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
        parsed = parse_qs(body, keep_blank_values=True)
        form = {key: values[0] for key, values in parsed.items()}
        result = run_agent(topic=form.get("topic", ""), domain=form.get("domain", ""), criteria=form.get("criteria", ""))
        self._send(_render_page(form=form, result=result, error=result.get("error", "")).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, data: bytes, *, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return


def build_parser():
    import argparse
    parser = argparse.ArgumentParser(description="Research Agent Bot dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Research Agent Bot dashboard running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
