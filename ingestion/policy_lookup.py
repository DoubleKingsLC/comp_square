"""
Policy file lookup — shared by the frontend and the batch harness.

Single source of truth for "which scraped policy documents apply to this
domain". Previously duplicated in frontend/app.py and evaluation/batch_audit.py,
which drifted: the batch harness learned about cross-domain policy hosting via
evaluation/policy_map.json while the frontend did not, so the frontend reported
"no policy documents found" for independent.ie even though the applicable
Mediahuis policy was already on disk.

Resolution order:
  1. exact domain match          policy_documents/<domain>_{privacy,cookie}_policy.md
  2. explicit override           evaluation/policy_map.json  (parent/group domains)
  3. filename stem heuristic     any *_policy.md whose name contains the site stem
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "policy_documents"
POLICY_MAP = ROOT / "evaluation" / "policy_map.json"


def find_policies(domain: str, verbose: bool = False) -> list[Path]:
    """Return the policy markdown files that apply to `domain`."""
    def log(msg):
        if verbose:
            print(msg)

    out: list[Path] = []
    for kind in ("privacy", "cookie"):
        p = POLICY_DIR / f"{domain}_{kind}_policy.md"
        if p.exists():
            out.append(p)
    if out:
        return out

    if POLICY_MAP.exists():
        try:
            mapping = json.loads(POLICY_MAP.read_text(encoding="utf-8"))
            for host in mapping.get(domain, []):
                for kind in ("privacy", "cookie"):
                    p = POLICY_DIR / f"{host}_{kind}_policy.md"
                    if p.exists():
                        out.append(p)
            if out:
                log(f"  [i] {domain}: using policies mapped from "
                    f"{', '.join(mapping.get(domain, []))}")
        except Exception as e:
            log(f"  [!] policy_map.json unreadable: {e}")
    if out:
        return out

    stem = domain.replace("www.", "").split(".")[0]
    if POLICY_DIR.exists():
        out = [p for p in POLICY_DIR.glob("*_policy.md") if stem in p.name]
    return out
