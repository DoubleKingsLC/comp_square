"""
comp_square — local web frontend (Phase 5)
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

A single-file Flask app that wraps the existing CLI pipeline:
  telemetry_collector.py -> har_extractor.py -> (policy_scraper_2.py) ->
  rag/scorer.py -> rag/report_builder.py

Run:
    source venv/bin/activate
    pip install flask
    export OPENAI_API_KEY=...        (or ANTHROPIC_API_KEY)
    python3 frontend/app.py
    -> open http://127.0.0.1:5001

Design notes:
  * Pipeline steps run in a background thread via subprocess, mirroring the
    exact CLI commands used manually — nothing behaves differently in the UI.
  * "Reuse existing artifacts" skips collection/scraping when HAR/telemetry/
    policy files for the domain already exist (fast, reliable demo path).
  * Single job at a time — this is a local research tool, not a service.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

app = Flask(__name__)

JOB: dict = {"state": "idle", "stage": "", "log": [], "report_html": None,
             "report_json": None, "started": None, "url": None}
LOCK = threading.Lock()

DIMENSION_PRESETS = {
    "demo": ["pre_consent_tracking", "tracking_without_consent", "disclosure_of_third_parties"],
    "behavioural": ["pre_consent_tracking", "consent_mechanism_validity", "tracking_without_consent",
                    "disclosure_of_data_collected", "disclosure_of_third_parties",
                    "cookie_retention_period", "cross_border_transfers", "data_minimisation"],
    "all": [],   # scorer default = all 15
}


def log(msg: str):
    with LOCK:
        JOB["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    print(msg, flush=True)


def set_stage(stage: str):
    with LOCK:
        JOB["stage"] = stage
    log(f"── {stage} ──")


def run_cmd(args: list[str], timeout: int = 420) -> bool:
    """Run a pipeline CLI, streaming its output into the job log."""
    log("$ " + " ".join(str(a) for a in args))
    try:
        proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                with LOCK:
                    JOB["log"].append(line)
        proc.wait(timeout=timeout)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        log(f"[!] timed out after {timeout}s")
        return False
    except Exception as e:
        log(f"[!] {e}")
        return False


def newest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(ROOT / pattern)), key=os.path.getmtime)
    return Path(files[-1]) if files else None


def find_policies(domain: str) -> list[Path]:
    """Policy files applying to this domain. Delegates to the shared lookup so
    the frontend and the batch harness cannot disagree (they did: the frontend
    was unaware of cross-domain policy hosting)."""
    sys.path.insert(0, str(ROOT))
    from ingestion.policy_lookup import find_policies as _find
    return _find(domain, verbose=True)


def capture_sanity_check(tele_path: Path):
    """Refuse to score a degenerate capture (bot-blocked / empty page).
    Observed on ndtv.com: 1 request, 0 UI elements → garbage-in scoring."""
    try:
        t = json.loads(tele_path.read_text(encoding="utf-8"))
        reqs = t.get("observed_behavior", {}).get("network_summary", {}).get("total_requests", 0)
        ui = t.get("visual_evidence", {}).get("interactable_elements", {}).get("total", 0)
    except Exception:
        return
    if reqs < 10 or ui == 0:
        raise RuntimeError(
            f"DEGENERATE CAPTURE — only {reqs} request(s) and {ui} UI element(s) "
            "recorded. The site almost certainly blocked the headless browser "
            "or served an empty page; scoring this would produce meaningless "
            "verdicts. Retry (some sites block intermittently), or scan a "
            "different site.")


def pipeline(url: str, preset: str, regulations: list[str], model: str, reuse: bool):
    domain = urlparse(url).netloc or url
    # Jurisdiction heuristic: Indian sites fall under the DPDP Act.
    if domain.endswith(".in") or ".in/" in url:
        if regulations and "DPDP" not in regulations:
            regulations = regulations + ["DPDP"]
            log("[i] .in domain detected — DPDP added to the regulation set")
    try:
        # 1. Telemetry ------------------------------------------------------
        har = newest(f"telemetry_output/{domain}_*.har") if reuse else None
        tele = newest(f"telemetry_output/{domain}_*_telemetry.json") if reuse else None
        if har and tele:
            set_stage(f"Telemetry: reusing {har.name}")
        else:
            set_stage("Telemetry: collecting (Playwright, ~60s)")
            if not run_cmd([PY, "telemetry_collector.py", url]):
                raise RuntimeError("telemetry collection failed")
            har = newest(f"telemetry_output/{domain}_*.har")
            tele = newest(f"telemetry_output/{domain}_*_telemetry.json")
            if not har:
                raise RuntimeError("no HAR produced")
        capture_sanity_check(tele)

        # 2. Behavioural evidence ------------------------------------------
        set_stage("Extracting behavioural evidence")
        evidence_path = ROOT / "telemetry_output" / f"{domain}_evidence.json"
        if not run_cmd([PY, "ingestion/har_extractor.py", str(har),
                        "--telemetry", str(tele), "--json", str(evidence_path)]):
            raise RuntimeError("har_extractor failed")

        # 3. Policies -------------------------------------------------------
        policies = find_policies(domain)
        if policies:
            set_stage(f"Policies: reusing {len(policies)} scraped file(s)")
        elif not reuse:
            set_stage("Policies: scraping")
            run_cmd([PY, "policy_scraper_2.py", url, str(tele)])
            policies = find_policies(domain)
        if not policies:
            log("[!] no policy documents found — scoring on behaviour only "
                "(policy treated as silent)")

        # 4. Scoring --------------------------------------------------------
        set_stage(f"Scoring ({model}, temperature 0)")
        cmd = [PY, "rag/scorer.py", "--domain", domain,
               "--har", str(har), "--telemetry", str(tele), "--model", model]
        for p in policies:
            cmd += ["--policy", str(p)]
        dims = DIMENSION_PRESETS.get(preset, [])
        if dims:
            cmd += ["--dimensions", *dims]
        if regulations:
            cmd += ["--regulations", *regulations]
        if not run_cmd(cmd, timeout=600):
            raise RuntimeError("scorer failed (is the API key exported and the "
                               "vector DB ingested?)")
        report_json = newest(f"compliance_reports/{domain}_*_report.json")
        if not report_json:
            raise RuntimeError("no report JSON produced")

        # 5. Report ---------------------------------------------------------
        set_stage("Rendering report")
        if not run_cmd([PY, "rag/report_builder.py", str(report_json),
                        "--evidence", str(evidence_path)]):
            raise RuntimeError("report_builder failed")
        report_html = report_json.with_suffix(".html")

        with LOCK:
            JOB.update(state="done", stage="Complete",
                       report_html=str(report_html), report_json=str(report_json))
        log(f"[✓] Done — {report_html.name}")
    except Exception as e:
        with LOCK:
            JOB.update(state="error", stage=f"Error: {e}")
        log(f"[✗] {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/run")
def api_run():
    with LOCK:
        if JOB["state"] == "running":
            return jsonify(error="a job is already running"), 409
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url.startswith("http"):
            url = "https://" + url
        JOB.update(state="running", stage="Starting", log=[], report_html=None,
                   report_json=None, started=time.time(), url=url)
    threading.Thread(target=pipeline, daemon=True, args=(
        url,
        data.get("preset", "demo"),
        data.get("regulations", ["GDPR", "PECR"]),
        data.get("model", "gpt-4o-mini"),
        bool(data.get("reuse", True)),
    )).start()
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    with LOCK:
        return jsonify({k: JOB[k] for k in
                        ("state", "stage", "log", "report_html", "url")})


@app.get("/report")
def report():
    with LOCK:
        path = JOB["report_html"]
    if not path or not Path(path).exists():
        return "No report yet", 404
    return send_file(path)


@app.get("/")
def index():
    return INDEX_HTML


INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>comp_square</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 *{box-sizing:border-box;margin:0}
 body{font:15px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;background:#F2F5FC;color:#1A1A2E}
 header{background:#1E2761;color:#fff;padding:22px 28px}
 h1{font-family:Cambria,Georgia,serif;font-size:24px}
 .sub{color:#CADCFC;font-size:12.5px;margin-top:2px}
 .wrap{max-width:980px;margin:24px auto;padding:0 20px}
 .card{background:#fff;border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:0 1px 4px #1E276114}
 label{font-size:12px;font-weight:600;color:#5A6178;display:block;margin:10px 0 4px}
 input[type=text],select{width:100%;padding:9px 12px;border:1px solid #C4CEE4;border-radius:8px;font-size:14px}
 .row{display:flex;gap:14px;flex-wrap:wrap}.row>div{flex:1;min-width:160px}
 .chk{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:13.5px}
 button{background:#1E2761;color:#fff;border:0;border-radius:8px;padding:11px 26px;font-size:15px;font-weight:600;cursor:pointer;margin-top:16px}
 button:disabled{opacity:.5;cursor:default}
 .stage{font-weight:700;color:#1E2761;margin-bottom:8px}
 .stage.err{color:#B3261E}.stage.ok{color:#2C5F2D}
 pre{background:#101430;color:#CADCFC;border-radius:10px;padding:14px;font-size:11.5px;
     max-height:340px;overflow:auto;white-space:pre-wrap;word-break:break-all}
 iframe{width:100%;height:900px;border:1px solid #C4CEE4;border-radius:12px;background:#fff}
 .hint{font-size:12px;color:#5A6178;margin-top:8px}
 a.btn{display:inline-block;background:#2C5F2D;color:#fff;text-decoration:none;border-radius:8px;
       padding:9px 20px;font-weight:600;margin:10px 8px 0 0;font-size:14px}
</style></head><body>
<header>
  <h1>comp_square — privacy compliance auditor</h1>
  <div class="sub">law + notice + practice, triangulated per dimension &middot; research prototype, findings are potential violations</div>
</header>
<div class="wrap">
  <div class="card">
    <label>Website URL</label>
    <input type="text" id="url" placeholder="https://www.example.com" value="https://www.independent.ie">
    <div class="row">
      <div><label>Dimensions</label>
        <select id="preset">
          <option value="demo">Demo — 3 key dimensions (fast)</option>
          <option value="behavioural">Behavioural — 8 dimensions</option>
          <option value="all">Full audit — all 15 dimensions</option>
        </select></div>
      <div><label>Regulations</label>
        <select id="regs">
          <option value="GDPR,PECR">GDPR + PECR (EU/UK)</option>
          <option value="GDPR,PECR,DPDP">GDPR + PECR + DPDP</option>
          <option value="DPDP">DPDP only (India)</option>
          <option value="GDPR">GDPR only</option>
          <option value="">All ingested</option>
        </select></div>
      <div><label>Model</label>
        <select id="model">
          <option>gpt-4o-mini</option><option>gpt-4o</option>
          <option>claude-haiku-4-5</option><option>claude-sonnet-4-6</option>
        </select></div>
    </div>
    <div class="chk"><input type="checkbox" id="reuse" checked>
      <span>Reuse existing telemetry &amp; policies if available (fast, reliable — untick to force a fresh crawl)</span></div>
    <button id="go" onclick="run()">Run audit</button>
    <div class="hint">Pipeline: Playwright telemetry → HAR evidence extraction → policy documents → RAG retrieval (ChromaDB) → LLM scoring (temp 0) → report.</div>
  </div>
  <div class="card" id="progress" style="display:none">
    <div class="stage" id="stage">Starting…</div>
    <pre id="log"></pre>
    <div id="done"></div>
  </div>
  <div class="card" id="reportcard" style="display:none">
    <iframe id="frame" src="about:blank"></iframe>
  </div>
</div>
<script>
let timer=null;
async function run(){
  const body={url:document.getElementById('url').value,
              preset:document.getElementById('preset').value,
              regulations:document.getElementById('regs').value?document.getElementById('regs').value.split(','):[],
              model:document.getElementById('model').value,
              reuse:document.getElementById('reuse').checked};
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){alert((await r.json()).error||'failed');return}
  document.getElementById('go').disabled=true;
  document.getElementById('progress').style.display='block';
  document.getElementById('reportcard').style.display='none';
  document.getElementById('done').innerHTML='';
  timer=setInterval(poll,1200); poll();
}
async function poll(){
  const s=await (await fetch('/api/status')).json();
  const st=document.getElementById('stage');
  st.textContent=s.stage||s.state; st.className='stage';
  const pre=document.getElementById('log');
  pre.textContent=s.log.join('\\n'); pre.scrollTop=pre.scrollHeight;
  if(s.state==='done'){
    clearInterval(timer); document.getElementById('go').disabled=false;
    st.className='stage ok';
    document.getElementById('done').innerHTML='<a class="btn" href="/report" target="_blank">Open report in new tab</a>';
    document.getElementById('reportcard').style.display='block';
    document.getElementById('frame').src='/report?t='+Date.now();
  } else if(s.state==='error'){
    clearInterval(timer); document.getElementById('go').disabled=false;
    st.className='stage err';
  }
}
</script>
</body></html>"""


if __name__ == "__main__":
    print("comp_square frontend → http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
