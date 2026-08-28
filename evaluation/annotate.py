"""
Ground-truth annotation harness — Phase 6 (evaluation)
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Produces the missing piece of the evaluation: an independent human judgement
to compare the scorer against, following the per-clause protocol of Xie et
al. (USENIX Sec 2025).

Two modes:

  --prepare   Build a BLINDED annotation sheet. For each (site, dimension) it
              lists the retrieved legal requirement, the observed behavioural
              evidence and the relevant policy excerpt, but NOT the system's
              verdict. Blinding matters: an annotator who can see the model's
              answer tends to agree with it, which would inflate the result.

  --score     Read the completed sheet, compare with the system verdicts, and
              report per-dimension and per-class precision / recall / F1,
              Cohen's kappa, and a confusion matrix, plus markdown tables for
              the paper.

Usage:
    python3 evaluation/annotate.py --prepare --limit 5
    #   → evaluation/results/annotation_sheet.csv   (fill in `human_verdict`)
    python3 evaluation/annotate.py --score

Label vocabulary (must match the scorer): PASS, FAIL, PARTIAL, NOT_ADDRESSED.
Leave a row blank to exclude it from scoring.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evaluation" / "results"
SHEET = OUT / "annotation_sheet.csv"

LABELS = ["PASS", "PARTIAL", "FAIL", "NOT_ADDRESSED"]

COLUMNS = ["domain", "dimension", "legal_requirement", "observed_behaviour",
           "policy_excerpt", "human_verdict", "annotator_notes"]


def newest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(ROOT / pattern)), key=os.path.getmtime)
    return Path(files[-1]) if files else None


def evidence_summary(ev: dict, dim_id: str, max_items: int = 6) -> str:
    """Compact, factual description of what was observed — no verdict language."""
    if not ev:
        return "no telemetry available"
    bits = []
    prof = (ev.get("pre_consent_profiling_cookies") or []) + \
           (ev.get("js_set_profiling_cookies") or [])
    tp = ev.get("third_party_domains") or []
    tr = ev.get("tracker_requests") or []
    fp = ev.get("fingerprinting_alarms") or []

    bits.append(f"consent UI present: {ev.get('consent_ui_detected')}")
    bits.append(f"profiling cookies before consent: {len(prof)}")
    if prof:
        bits.append("  " + "; ".join(
            f"{c.get('name')} ({c.get('cookie_domain')}, "
            f"{int(c['lifetime_days']) if c.get('lifetime_days') else 'session'}d)"
            for c in prof[:max_items]))
    bits.append(f"third-party domains: {len(tp)}")
    if tp:
        bits.append("  " + ", ".join(tp[:max_items]) + (" …" if len(tp) > max_items else ""))
    bits.append(f"tracker requests: {len(tr)}")
    if tr:
        doms = sorted({t.get("domain") for t in tr if isinstance(t, dict) and t.get("domain")})
        bits.append("  " + ", ".join(doms[:max_items]))
    bits.append(f"fingerprinting API calls: {len(fp)}")
    if fp:
        bits.append("  " + "; ".join(a.split("COMPLIANCE_ALARM: ")[-1][:60] for a in fp[:3]))
    dva = ev.get("declared_vs_actual") or {}
    if dva.get("undeclared_domains"):
        bits.append(f"domains observed but not named in policy: "
                    f"{len(dva['undeclared_domains'])}")
    return "\n".join(bits)


def policy_excerpt(policies: list[Path], dim_id: str, width: int = 900) -> str:
    """Keyword-selected passage of the policy relevant to this dimension."""
    keys = {
        "pre_consent_tracking": ["consent", "cookie", "before"],
        "tracking_without_consent": ["tracking", "tracker", "cookie", "consent", "fingerprint"],
        "disclosure_of_third_parties": ["third part", "partner", "share", "recipient", "vendor"],
        "disclosure_of_data_collected": ["collect", "information we", "data we"],
        "cookie_retention_period": ["retention", "retain", "how long", "expire"],
        "cross_border_transfers": ["transfer", "outside", "third countr", "international"],
        "childrens_data": ["child", "under 16", "under 13", "minor"],
        "data_subject_rights": ["right to", "access", "erasure", "portability"],
        "consent_mechanism_validity": ["consent", "withdraw", "manage", "preferences"],
    }.get(dim_id, ["policy"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in policies if p.exists())
    if not text:
        return "NO POLICY RETRIEVED"
    low = text.lower()

    def prose_score(window: str) -> float:
        """Prefer substantive prose over navigation. Tables of contents and
        link lists match the same keywords but tell the annotator nothing."""
        links = window.count("](") + window.count("](#")
        bullets = window.count("\n-") + window.count("\n*")
        sentences = window.count(". ")
        return sentences * 2 - links * 3 - bullets

    best, best_score = None, float("-inf")
    for k in keys:
        start = 0
        while True:
            i = low.find(k, start)
            if i == -1:
                break
            s = max(0, i - 200)
            window = text[s:s + width]
            sc = prose_score(window)
            if sc > best_score:
                best, best_score = window, sc
            start = i + 1
    if best is None:
        best = text[:width]
    return " ".join(best.split()).strip()


def find_policies(domain: str) -> list[Path]:
    import sys
    sys.path.insert(0, str(ROOT))
    from evaluation.batch_audit import find_policies as fp
    return fp(domain)


def prepare(limit: int | None, dimensions: list[str] | None):
    recs_path = OUT / "batch_results.json"
    if not recs_path.exists():
        raise SystemExit("run evaluation/batch_audit.py first")
    recs = json.loads(recs_path.read_text(encoding="utf-8"))
    scored = [r for r in recs if r.get("report")]
    if limit:
        scored = scored[:limit]

    rows = []
    for r in scored:
        domain = r["domain"]
        report = json.loads((ROOT / r["report"]).read_text(encoding="utf-8"))
        ev_path = ROOT / "telemetry_output" / f"{domain}_evidence.json"
        ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
        pols = find_policies(domain)
        for d in report.get("dimensions", []):
            if d.get("verdict") == "DRY_RUN":
                continue
            if dimensions and d["dimension"] not in dimensions:
                continue
            rule = (d.get("rule_text") or "")[:700].replace("\n", " ").strip()
            rows.append({
                "domain": domain,
                "dimension": d["dimension"],
                "legal_requirement": rule or "(no rule text recorded)",
                "observed_behaviour": evidence_summary(ev, d["dimension"]),
                "policy_excerpt": policy_excerpt(pols, d["dimension"]),
                "human_verdict": "",
                "annotator_notes": "",
            })

    OUT.mkdir(parents=True, exist_ok=True)
    with open(SHEET, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"[✓] {SHEET}")
    print(f"    {len(rows)} rows across {len(scored)} sites "
          f"({len(set(r['dimension'] for r in rows))} dimensions)")
    print(f"    System verdicts are deliberately NOT included: annotate blind, "
          f"then run --score.")
    print(f"    Fill the 'human_verdict' column with one of: {', '.join(LABELS)}")


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────
def system_verdicts() -> dict[tuple[str, str], str]:
    recs = json.loads((OUT / "batch_results.json").read_text(encoding="utf-8"))
    out = {}
    for r in recs:
        if not r.get("report"):
            continue
        rep = json.loads((ROOT / r["report"]).read_text(encoding="utf-8"))
        for d in rep.get("dimensions", []):
            if d.get("verdict") != "DRY_RUN":
                out[(r["domain"], d["dimension"])] = d["verdict"]
    return out


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def cohens_kappa(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    labels = sorted({x for pr in pairs for x in pr})
    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b) / n
    pe = 0.0
    for l in labels:
        pa = sum(1 for a, _ in pairs if a == l) / n
        pb = sum(1 for _, b in pairs if b == l) / n
        pe += pa * pb
    return (agree - pe) / (1 - pe) if pe < 1 else 1.0


def score():
    if not SHEET.exists():
        raise SystemExit(f"{SHEET} not found — run --prepare first")
    sysv = system_verdicts()
    pairs, per_dim = [], {}
    missing = 0
    with open(SHEET, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            human = (row.get("human_verdict") or "").strip().upper()
            if not human:
                continue
            if human not in LABELS:
                print(f"[!] unrecognised label '{human}' for {row['domain']}/{row['dimension']} — skipped")
                continue
            key = (row["domain"], row["dimension"])
            if key not in sysv:
                missing += 1
                continue
            pairs.append((human, sysv[key]))
            per_dim.setdefault(row["dimension"], []).append((human, sysv[key]))

    if not pairs:
        raise SystemExit("no completed rows found — fill in the human_verdict column")

    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    L = ["# Ground-truth comparison", "",
         f"{n} annotated judgements across {len(per_dim)} dimensions. "
         f"Annotation was blind to the system verdict.", "",
         f"- Exact agreement: **{agree}/{n} ({agree/n:.0%})**",
         f"- Cohen's kappa: **{cohens_kappa(pairs):.2f}**", ""]

    # Per-class P/R/F1
    L += ["## Per-verdict-class agreement", "",
          "| Verdict | Human (n) | System (n) | Precision | Recall | F1 |", "|---|---|---|---|---|---|"]
    f1s = []
    for lab in LABELS:
        tp = sum(1 for h, s in pairs if h == lab and s == lab)
        fp_ = sum(1 for h, s in pairs if h != lab and s == lab)
        fn = sum(1 for h, s in pairs if h == lab and s != lab)
        hn = sum(1 for h, _ in pairs if h == lab)
        sn = sum(1 for _, s in pairs if s == lab)
        p, r, f = prf(tp, fp_, fn)
        if hn or sn:
            f1s.append(f)
            L.append(f"| {lab} | {hn} | {sn} | {p:.2f} | {r:.2f} | {f:.2f} |")
    L += ["", f"Macro-average F1: **{(sum(f1s)/len(f1s) if f1s else 0):.2f}**", ""]

    # Binary view: did the system flag a problem at all?
    def concern(v):
        return v in ("FAIL", "PARTIAL")
    tp = sum(1 for h, s in pairs if concern(h) and concern(s))
    fp_ = sum(1 for h, s in pairs if not concern(h) and concern(s))
    fn = sum(1 for h, s in pairs if concern(h) and not concern(s))
    p, r, f = prf(tp, fp_, fn)
    L += ["## Binary view: was a compliance concern raised?", "",
          f"Treating FAIL and PARTIAL as “concern raised”: precision **{p:.2f}**, "
          f"recall **{r:.2f}**, F1 **{f:.2f}** (TP {tp}, FP {fp_}, FN {fn}).", ""]

    # Per dimension
    L += ["## Per-dimension agreement", "",
          "| Dimension | n | Exact agreement | Kappa |", "|---|---|---|---|"]
    for dim, prs in sorted(per_dim.items()):
        a = sum(1 for h, s in prs if h == s)
        L.append(f"| {dim} | {len(prs)} | {a}/{len(prs)} ({a/len(prs):.0%}) | "
                 f"{cohens_kappa(prs):.2f} |")
    L.append("")

    # Confusion matrix
    present = [l for l in LABELS if any(h == l or s == l for h, s in pairs)]
    L += ["## Confusion matrix (rows = human, columns = system)", "",
          "| | " + " | ".join(present) + " |", "|---" * (len(present) + 1) + "|"]
    for h in present:
        cells = [str(sum(1 for a, b in pairs if a == h and b == s)) for s in present]
        L.append(f"| **{h}** | " + " | ".join(cells) + " |")
    L += ["", "Cells off the diagonal are disagreements. Read them directionally: "
              "system verdicts to the right of the diagonal are more severe than the "
              "human judgement, to the left more lenient.", ""]

    if missing:
        L.append(f"*{missing} annotated row(s) had no matching system verdict and were skipped.*")

    out = OUT / "ground_truth.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[✓] {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Blinded ground-truth annotation and scoring.")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--limit", type=int, help="number of sites to include when preparing")
    ap.add_argument("--dimensions", nargs="*", help="restrict to these dimension ids")
    args = ap.parse_args()

    if args.prepare:
        prepare(args.limit, args.dimensions)
    elif args.score:
        score()
    else:
        ap.print_help()
