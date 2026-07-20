"""
Compliance Report Builder — Phase 5
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Renders the scorer's JSON report as a single self-contained HTML file
(inline CSS, no JS, no external assets — opens offline in any browser).

Usage:
    python3 rag/report_builder.py compliance_reports/www.independent.ie_20260712_report.json
    python3 rag/report_builder.py <report.json> --evidence <evidence.json> --out report.html

Optionally attach the har_extractor evidence dict (--evidence) to append a
behavioural-evidence appendix (third-party domains, fingerprinting alarms).
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

NAVY = "#1E2761"
INK = "#1A1A2E"
MUT = "#5A6178"
CARD = "#F2F5FC"
RED = "#B3261E"
GREEN = "#2C5F2D"
AMBER = "#9A6A00"
GREY = "#6B7280"

VERDICT_STYLE = {
    "PASS":          (GREEN, "#E8F1E9"),
    "FAIL":          (RED,   "#FBEAE8"),
    "PARTIAL":       (AMBER, "#FAF3E0"),
    "NOT_ADDRESSED": (GREY,  "#EEF0F3"),
    "ERROR":         (GREY,  "#EEF0F3"),
}

DISCREPANCY_LABEL = {
    "neglect":    "Neglect — behaviour observed that the policy never discloses",
    "contrary":   "Contrary — policy claims the opposite of observed behaviour",
    "inadequate": "Inadequate — policy mentions the practice but too vaguely",
}


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def score_color(score) -> str:
    if score is None:
        return GREY
    return GREEN if score >= 75 else AMBER if score >= 50 else RED


def dimension_card(d: dict) -> str:
    verdict = d.get("verdict", "ERROR")
    vcol, vbg = VERDICT_STYLE.get(verdict, VERDICT_STYLE["ERROR"])
    score = d.get("score")
    sw = 0 if score is None else max(2, score)
    breach = d.get("breach") or {}
    cite = ""
    if breach.get("regulation"):
        cite = f"{breach.get('regulation','')} Art. {breach.get('article','')}"
    conf = d.get("confidence")
    conf_s = f"{conf:.0%}" if isinstance(conf, (int, float)) else "—"
    disc = d.get("discrepancy_type")

    rows = []
    if breach.get("requirement_text"):
        rows.append(("Legal requirement", f"<em>“{esc(breach['requirement_text'])}”</em> <span class='cite'>({esc(cite)})</span>"))
    if d.get("policy_claim"):
        sec = f" <span class='cite'>— section: {esc(d.get('policy_section'))}</span>" if d.get("policy_section") else ""
        rows.append(("Policy claim (notice)", f"“{esc(d['policy_claim'])}”{sec}"))
    if d.get("behavioral_evidence"):
        rows.append(("Observed behaviour (practice)", esc(d["behavioral_evidence"])))
    if disc:
        rows.append(("Discrepancy", f"<b>{esc(DISCREPANCY_LABEL.get(disc, disc))}</b>"))
    if d.get("explanation"):
        rows.append(("Assessment", esc(d["explanation"])))
    if d.get("recommendation"):
        rows.append(("Recommended fix", esc(d["recommendation"])))

    rows_html = "".join(
        f"<div class='row'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in rows)

    return f"""
    <div class="dim">
      <div class="dimhead">
        <div>
          <span class="badge" style="color:{vcol};background:{vbg};border:1px solid {vcol}33">{esc(verdict.replace('_',' '))}</span>
          <span class="dimname">{esc(d.get('dimension',''))}</span>
          <span class="cite">{esc(cite)}</span>
        </div>
        <div class="dimscore" style="color:{score_color(score)}">{'' if score is None else score}<span class="of">{'' if score is None else ' / 100'}</span></div>
      </div>
      <div class="bar"><div class="fill" style="width:{sw}%;background:{score_color(score)}"></div></div>
      <div class="meta">severity: {esc(d.get('severity','—'))} &nbsp;·&nbsp; confidence: {conf_s}</div>
      {rows_html}
    </div>"""


def evidence_appendix(ev: dict) -> str:
    if not ev:
        return ""
    tp = ev.get("third_party_domains", [])
    fp = ev.get("fingerprinting_alarms", [])
    prof = (ev.get("pre_consent_profiling_cookies") or []) + (ev.get("js_set_profiling_cookies") or [])
    items = []
    if prof:
        cookies = "".join(
            f"<li><code>{esc(c.get('name'))}</code> ({esc(c.get('cookie_domain'))}) — "
            f"{'session' if not c.get('lifetime_days') else str(int(c['lifetime_days'])) + ' days'}</li>" for c in prof)
        items.append(f"<h3>Potential pre-consent profiling cookies ({len(prof)})</h3><ul>{cookies}</ul>")
    if tp:
        doms = "".join(f"<li><code>{esc(d)}</code></li>" for d in tp)
        items.append(f"<h3>Third-party domains contacted ({len(tp)})</h3><ul class='cols'>{doms}</ul>")
    if fp:
        alarms = "".join(f"<li>{esc(a)}</li>" for a in fp)
        items.append(f"<h3>Fingerprinting API calls ({len(fp)})</h3><ul>{alarms}</ul>")
    if not items:
        return ""
    proto = esc(ev.get("consent_interaction", ""))
    mode = esc(ev.get("tracker_list_mode", ""))
    return f"""
    <div class="section">
      <h2>Appendix — behavioural evidence</h2>
      <div class="meta">Audit protocol: {proto} &nbsp;·&nbsp; tracker classification: {mode} &nbsp;·&nbsp; consent UI detected: {esc(ev.get('consent_ui_detected'))}</div>
      {''.join(items)}
    </div>"""


def build_html(report: dict, evidence: dict | None = None) -> str:
    overall = report.get("overall_score")
    overall_verdict = esc(report.get("overall_verdict", "")).replace("_", " ")
    ocol = score_color(overall)
    dims = sorted(report.get("dimensions", []),
                  key=lambda d: (d.get("score") is None, d.get("score", 101)))
    cards = "".join(dimension_card(d) for d in dims if d.get("verdict") != "DRY_RUN")
    gen = datetime.now().strftime("%d %b %Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Compliance report — {esc(report.get('domain'))}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ font: 15px/1.55 -apple-system, 'Segoe UI', Roboto, sans-serif; color: {INK}; background: #fff; }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 0 24px 60px; }}
  header {{ background: {NAVY}; color: #fff; padding: 36px 0 30px; }}
  header .wrap {{ padding-bottom: 0; }}
  h1 {{ font-family: Cambria, Georgia, serif; font-size: 30px; }}
  .sub {{ color: #CADCFC; margin-top: 6px; font-size: 13.5px; }}
  .overall {{ display: flex; align-items: center; gap: 22px; margin-top: 22px; }}
  .onum {{ font-family: Cambria, Georgia, serif; font-size: 64px; font-weight: bold; line-height: 1; }}
  .overdict {{ font-size: 15px; font-weight: 600; letter-spacing: .04em; }}
  .disclaimer {{ background: #2A3878; color: #CADCFC; font-size: 12px; padding: 9px 14px; border-radius: 8px; margin: 20px 0 26px; }}
  h2 {{ font-family: Cambria, Georgia, serif; color: {NAVY}; font-size: 21px; margin: 34px 0 14px; }}
  h3 {{ color: {NAVY}; font-size: 14.5px; margin: 18px 0 6px; }}
  .dim {{ background: {CARD}; border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }}
  .dimhead {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }}
  .dimname {{ font-weight: 700; font-size: 16px; margin: 0 8px; }}
  .badge {{ font-size: 11px; font-weight: 700; letter-spacing: .05em; padding: 3px 9px; border-radius: 20px; vertical-align: 2px; }}
  .cite {{ color: {MUT}; font-size: 12.5px; }}
  .dimscore {{ font-family: Cambria, Georgia, serif; font-size: 30px; font-weight: bold; }}
  .of {{ font-size: 13px; color: {MUT}; font-weight: normal; }}
  .bar {{ height: 6px; background: #E2E7F2; border-radius: 3px; margin: 10px 0 6px; }}
  .fill {{ height: 100%; border-radius: 3px; }}
  .meta {{ color: {MUT}; font-size: 12.5px; margin-bottom: 10px; }}
  .row {{ display: flex; gap: 14px; padding: 7px 0; border-top: 1px solid #E2E7F2; }}
  .k {{ flex: 0 0 190px; color: {MUT}; font-size: 12.5px; font-weight: 600; padding-top: 1px; }}
  .v {{ flex: 1; font-size: 13.5px; }}
  ul {{ margin: 4px 0 4px 22px; font-size: 13px; }}
  ul.cols {{ columns: 3; }}
  code {{ background: #E9EDF7; padding: 1px 5px; border-radius: 4px; font-size: 12px; }}
  .section {{ margin-top: 10px; }}
  footer {{ color: {MUT}; font-size: 11.5px; margin-top: 40px; border-top: 1px solid #E2E7F2; padding-top: 12px; }}
</style></head>
<body>
<header><div class="wrap">
  <h1>Privacy-compliance audit — {esc(report.get('domain'))}</h1>
  <div class="sub">Scanned {esc((report.get('scan_date') or '')[:10])} · model {esc(report.get('model'))} ·
    regulations: {esc(', '.join(report.get('regulations_filter') or []) or 'all')} ·
    {len([d for d in report.get('dimensions', []) if d.get('verdict') != 'DRY_RUN'])} dimensions scored</div>
  <div class="overall">
    <div class="onum" style="color:#fff">{'' if overall is None else overall}<span style="font-size:20px;color:#CADCFC"> / 100</span></div>
    <div>
      <div class="overdict" style="color:#CADCFC">{overall_verdict}</div>
      <div class="sub">severity-weighted across scored dimensions · NOT ADDRESSED excluded</div>
    </div>
  </div>
</div></header>
<div class="wrap">
  <div class="disclaimer">{esc(report.get('disclaimer', ''))}</div>
  <h2>Findings by dimension <span class="cite" style="font-weight:normal">(worst first)</span></h2>
  {cards}
  {evidence_appendix(evidence or {})}
  <footer>comp_square — LLM-Driven Privacy Compliance Framework · Aaron Joseph Jean, University of Galway ·
  generated {gen} · law + notice + practice triangulated per dimension; all findings are potential violations pending legal review.</footer>
</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Render a scorer JSON report as self-contained HTML.")
    ap.add_argument("report", help="Path to compliance_reports/<domain>_<date>_report.json")
    ap.add_argument("--evidence", help="Optional har_extractor evidence JSON for the appendix")
    ap.add_argument("--out", help="Output HTML path (default: alongside the JSON)")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8")) if args.evidence else None

    out = Path(args.out) if args.out else Path(args.report).with_suffix(".html")
    out.write_text(build_html(report, evidence), encoding="utf-8")
    print(f"[✓] Report written to {out}")
    print("    Open it in a browser — no server needed.")


if __name__ == "__main__":
    main()
