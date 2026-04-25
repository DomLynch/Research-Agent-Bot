from __future__ import annotations

import html
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from agent.cli import run_agent
from agent.submit import check_decision

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
    ".status-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}"
    ".bar{height:12px;background:#c8dcdd;border:1px solid var(--line);border-radius:999px;overflow:hidden}"
    ".bar>div{height:100%;width:0;background:linear-gradient(90deg,#295b62,#7ba8a8);transition:width .25s ease}"
    ".log{margin-top:12px;display:grid;gap:6px;color:var(--muted);font-size:14px}"
    ".log div{padding:6px 8px;border-left:3px solid var(--line);background:rgba(255,255,255,.35);border-radius:8px}"
    "pre{overflow:auto;background:#fbf8f3;padding:16px;border-radius:12px;border:1px solid var(--line);white-space:pre-wrap}"
)

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 50


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _trim_jobs_locked() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    old_done = sorted(
        (item for item in _JOBS.items() if item[1].get("status") in {"done", "error"}),
        key=lambda item: float(item[1].get("updated_at", 0)),
    )
    for job_id, _ in old_done[: max(0, len(_JOBS) - _MAX_JOBS)]:
        _JOBS.pop(job_id, None)


def _job_snapshot(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = dict(_JOBS.get(job_id) or {})
        if not job:
            return {}
        return {"id": job_id, "status": job.get("status", "unknown"), "done": job.get("status") in {"done", "error"}, "progress": job.get("progress") or {}, "events": list(job.get("events") or [])[-12:], "error": job.get("error", ""), "result_error": (job.get("result") or {}).get("error", "")}


def _update_job(job_id: str, event: dict) -> None:
    safe = {"percent": int(event.get("percent", 0) or 0), "step": str(event.get("step") or "running"), "message": str(event.get("message") or ""), "time": time.strftime("%H:%M:%S")}
    for key in ("retrieved", "selected", "queries", "high_severity"):
        if key in event:
            safe[key] = event[key]
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["progress"] = safe
        job.setdefault("events", []).append(safe)
        job["updated_at"] = time.time()


def _start_job(form: dict[str, str]) -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {"form": dict(form), "status": "running", "progress": {"percent": 0, "step": "queued", "message": "Run accepted by dashboard."}, "events": [], "result": None, "error": "", "updated_at": time.time()}
        _trim_jobs_locked()

    def worker() -> None:
        try:
            result = run_agent(topic=form.get("topic", ""), domain=form.get("domain", ""), criteria=form.get("criteria", ""), progress=lambda event: _update_job(job_id, event))
            with _JOBS_LOCK:
                job = _JOBS[job_id]
                job["result"] = result
                job["status"] = "done"
                job["error"] = str(result.get("error") or "")
                job["updated_at"] = time.time()
        except Exception as exc:
            _update_job(job_id, {"percent": 100, "step": "error", "message": str(exc)})
            with _JOBS_LOCK:
                job = _JOBS[job_id]
                job["status"] = "error"
                job["error"] = str(exc)
                job["updated_at"] = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def _render_page(*, form: dict[str, str], result: dict | None = None, error: str = "", job_id: str = "") -> str:
    error_block = f'<section class="panel error"><strong>{_esc(error)}</strong></section>' if error else ""
    status_block = ""
    if job_id:
        job_json = json.dumps(job_id)
        status_block = (
            '<section class="panel" id="run-status">'
            '<div class="status-head"><h2>Run Status</h2><strong id="pct">0%</strong></div>'
            '<div class="bar"><div id="bar"></div></div>'
            '<p id="status-msg">Queued.</p>'
            '<div class="log" id="status-log"></div>'
            "<script>"
            f"const jobId={job_json};"
            "function esc(s){return String(s||'').replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[m]));}"
            "async function poll(){"
            "const r=await fetch('/job/'+jobId,{cache:'no-store'});"
            "if(!r.ok){document.getElementById('status-msg').textContent='Status unavailable.';return;}"
            "const j=await r.json(); const p=j.progress||{}; const pct=Math.max(0,Math.min(100,p.percent||0));"
            "document.getElementById('pct').textContent=pct+'%';"
            "document.getElementById('bar').style.width=pct+'%';"
            "document.getElementById('status-msg').textContent=(p.step? p.step+': ':'')+(p.message||'Running.');"
            "document.getElementById('status-log').innerHTML=(j.events||[]).map(e=>'<div><strong>'+esc(e.time)+'</strong> '+esc(e.step)+': '+esc(e.message)+'</div>').join('');"
            "if(j.done){window.location='/result/'+jobId;return;}"
            "setTimeout(poll,1500);"
            "} poll();"
            "</script></section>"
        )
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
            sub_id = sub.get("submission", {}).get("id") or result.get("submission_id")
            decision = sub.get("decision", {})
            if sub_id:
                dec_status = decision.get("status", "pending")
                dec_verdict = decision.get("decision") or "pending"
                gates = decision.get("gate_failures", [])
                gate_str = "; ".join(g["reason"] for g in gates) if gates else "all passed"
                pub_str = ""
                status_link = ""
                if decision.get("publication_id"):
                    pub_str = f"<div><label>Publication</label><strong>{_esc(str(decision['publication_id'])[:8])}…</strong></div>"
                if dec_status in ("queued", "pending"):
                    status_link = f'<div><label>Status</label><a class="button secondary" href="/status/{quote(sub_id, safe="")}">Refresh status</a></div>'
                sub_block = (
                    f"<div><label>Submission</label><strong>{_esc(sub_id[:8])}…</strong></div>"
                    f"<div><label>Decision</label><strong>{_esc(dec_verdict)} ({_esc(dec_status)})</strong></div>"
                    f"<div><label>Intake Gates</label><strong>{_esc(gate_str)}</strong></div>"
                    f"{status_link}"
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
        f"{status_block}{result_block}</div></body></html>"
    )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/job/"):
            job_id = parsed.path.split("/job/", 1)[1]
            snapshot = _job_snapshot(job_id)
            if not snapshot:
                self._send(b'{"error":"job not found"}', status=404, content_type="application/json; charset=utf-8")
                return
            self._send(json.dumps(snapshot).encode("utf-8"), content_type="application/json; charset=utf-8")
            return
        if parsed.path.startswith("/result/"):
            job_id = parsed.path.split("/result/", 1)[1]
            with _JOBS_LOCK:
                job = dict(_JOBS.get(job_id) or {})
            if not job:
                self.send_error(404)
                return
            result = job.get("result") or {}
            self._send(_render_page(form=job.get("form") or {}, result=result, error=str(result.get("error") or job.get("error") or "")).encode("utf-8"))
            return
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
        if parsed.path.startswith("/status/"):
            sub_id = parsed.path.split("/status/", 1)[1]
            decision = check_decision(sub_id)
            # find the run log that contains this submission
            import json as _json
            run_data = {"submission": {"submission": {"id": sub_id}, "decision": decision}}
            for f in sorted(Path("runs").glob("*.json"), reverse=True):
                if f.name.endswith(".raw.json"):
                    continue
                try:
                    data = _json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if data.get("submission_id") == sub_id or data.get("submission", {}).get("submission", {}).get("id") == sub_id:
                    data["submission"]["decision"] = decision
                    run_data = data
                    break
            self._send(_render_page(form={}, result=run_data).encode("utf-8"))
            return
        self._send(_render_page(form={}).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        form = {key: values[0] for key, values in parsed.items()}
        job_id = _start_job(form)
        self._send(_render_page(form=form, job_id=job_id).encode("utf-8"), status=202)

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
