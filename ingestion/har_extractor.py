"""
HAR Behavioral Evidence Extractor — Phase 2 (runtime utility)
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Parses a Playwright-recorded .har file plus the matching *_telemetry.json
produced by telemetry_collector.py and returns a structured evidence dict
for direct injection into the RAG scorer prompt (NOT upserted to vector DB).

Methodology adopted from the literature:
  * Trevisan et al. (PoPETs 2019) — conservative "profiling cookie" rule:
      a cookie is profiling iff
        (1) it is third-party (eTLD+1 differs from the visited site), AND
        (2) its domain is classified as an advertising/analytics tracker by
            the INTERSECTION of two independent tracker lists, AND
        (3) its lifetime is >= 30 days.
      Because telemetry_collector.py performs NO interaction with the page
      (no scrolling, no clicks — Trevisan's clean-profile protocol), every
      cookie observed is by construction set BEFORE any user consent.
  * Bouhoula et al. (USENIX Sec 2024) — conservative tuning: prefer false
      negatives over false positives; violations reported as "potential".
  * Xiao et al., Lalaine (USENIX Sec 2023) — discrepancy typology used for
      declared-vs-actual comparison: neglect / contrary / inadequate.

Usage (runtime):
    from ingestion.har_extractor import extract
    evidence = extract("telemetry_output/www.example.com_20260305.har",
                       telemetry="telemetry_output/www.example.com_20260305_telemetry.json")

CLI:
    python3 ingestion/har_extractor.py telemetry_output/site.har \
        --telemetry telemetry_output/site_telemetry.json [--json out.json]

    python3 ingestion/har_extractor.py --update-lists   # refresh tracker lists
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

# ─────────────────────────────────────────────────────────────────────────────
# eTLD+1 helpers (kept in sync with telemetry_collector.py)
# ─────────────────────────────────────────────────────────────────────────────
MULTI_TLDS = {
    "co.uk", "org.uk", "me.uk", "net.uk", "ac.uk",
    "co.in", "org.in", "net.in", "ac.in",
    "co.au", "com.au", "net.au", "org.au",
    "co.nz", "com.nz", "co.za", "com.br",
    "co.jp", "ne.jp", "or.jp", "ac.jp",
    # private public-suffix registries (found via independent.ie scan:
    # api.kaching.eu.com wrongly collapsed to "eu.com")
    "eu.com", "us.com", "uk.com", "de.com", "gb.com", "cn.com",
    "jpn.com", "za.com", "br.com", "sa.com", "se.com", "ru.com",
    "uk.net", "gb.net", "se.net",
}


def get_etld1(hostname: str) -> str:
    """Return the registrable domain (eTLD+1) for a hostname."""
    hostname = (hostname or "").lower().lstrip(".")
    parts = hostname.split(".")
    if len(parts) <= 1:
        return hostname
    two_part = ".".join(parts[-2:])
    if two_part in MULTI_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return two_part


def is_third_party(hostname: str, first_party_etld1: str) -> bool:
    if not hostname:
        return False
    return get_etld1(hostname) != first_party_etld1


# ─────────────────────────────────────────────────────────────────────────────
# Tracker lists
#
# Primary list  : Disconnect (disconnect.me) services.json — category map.
# Secondary list: Ghostery/WhoTracks.me trackerdb domains.
# Profiling classification requires membership in the INTERSECTION of both
# (Trevisan et al.'s conservative rule). If only one list is available the
# extractor falls back to that list alone and flags the result as less strict.
#
# A built-in fallback of well-known advertising/analytics tracker eTLD+1
# domains (drawn from Trevisan et al. Table 2 and common tracker corpora) is
# bundled so the extractor works offline out of the box.
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent / "data"
DISCONNECT_PATH = DATA_DIR / "disconnect_services.json"
SECONDARY_PATH = DATA_DIR / "secondary_tracker_domains.txt"

DISCONNECT_URL = (
    "https://raw.githubusercontent.com/disconnectme/"
    "disconnect-tracking-protection/master/services.json"
)
# Ghostery's open tracker database — published as a release asset.
# License: CC-BY-NC-SA-4.0 (free for non-commercial/academic use).
SECONDARY_URL = (
    "https://github.com/ghostery/trackerdb/releases/latest/download/trackerdb.json"
)

# Ghostery trackerdb categories that indicate profiling/tracking use.
# Conservative: advertising + analytics only ("AA cookies", Bouhoula et al.).
GHOSTERY_PROFILING_CATEGORIES = {"advertising", "site_analytics", "pornvertising"}

# Advertising/analytics trackers appearing in Trevisan et al. Table 2 and other
# major corpora. eTLD+1 form. Used when downloaded lists are unavailable.
BUILTIN_TRACKER_DOMAINS = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "googletagservices.com",
    "facebook.net", "adnxs.com", "rubiconproject.com", "advertising.com",
    "adsrvr.org", "mathtag.com", "mookie1.com", "demdex.net", "bluekai.com",
    "bidswitch.net", "openx.net", "adform.net", "adformdsp.net",
    "smartadserver.com", "rfihub.com", "criteo.com", "criteo.net",
    "taboola.com", "outbrain.com", "hotjar.com", "scorecardresearch.com",
    "quantserve.com", "pubmatic.com", "casalemedia.com", "amazon-adsystem.com",
    "yandex.ru", "mc.yandex.ru", "chartbeat.com", "moatads.com",
    "krxd.net", "turn.com", "exelator.com", "agkn.com", "everesttech.net",
    "tapad.com", "sharethrough.com", "teads.tv", "yieldlab.net", "adition.com",
    "branch.io", "mixpanel.com", "segment.io", "segment.com", "amplitude.com",
    "tiktok.com", "ads-twitter.com", "linkedin.com", "bing.com",
    "clarity.ms", "doubleverify.com", "adsafeprotected.com", "id5-sync.com",
}

# Disconnect categories that indicate profiling/tracking use.
PROFILING_CATEGORIES = {"Advertising", "Analytics", "FingerprintingInvasive", "FingerprintingGeneral"}

PROFILING_LIFETIME_DAYS = 30  # Trevisan et al.: >= 1 month


class TrackerDB:
    """Loads tracker lists and classifies domains."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.disconnect: dict[str, str] = {}   # etld1 -> category
        self.secondary: set[str] = set()       # etld1 set
        self._load()

    # -- loading ------------------------------------------------------------
    def _load(self) -> None:
        if DISCONNECT_PATH.exists():
            try:
                raw = json.loads(DISCONNECT_PATH.read_text(encoding="utf-8"))
                for category, services in raw.get("categories", {}).items():
                    for service in services:            # [{name: {homepage: [domains]}}]
                        for _name, urls in service.items():
                            for _homepage, domains in urls.items():
                                if isinstance(domains, list):
                                    for d in domains:
                                        self.disconnect[get_etld1(d)] = category
            except Exception as e:                       # pragma: no cover
                print(f"[!] Failed to parse Disconnect list: {e}", file=sys.stderr)

        if SECONDARY_PATH.exists():
            try:
                self.secondary = {
                    get_etld1(line.strip())
                    for line in SECONDARY_PATH.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")
                }
            except Exception as e:                       # pragma: no cover
                print(f"[!] Failed to parse secondary list: {e}", file=sys.stderr)

    @property
    def mode(self) -> str:
        """How strict is the classification we can offer?"""
        if self.disconnect and self.secondary:
            return "intersection"        # Trevisan-strict
        if self.disconnect or self.secondary:
            return "single-list"
        return "builtin-fallback"

    # -- classification -----------------------------------------------------
    def is_profiling_tracker(self, hostname: str) -> bool:
        """True if the hostname's eTLD+1 is an advertising/analytics tracker
        under the strictest classification currently available."""
        d = get_etld1(hostname)
        if self.mode == "intersection":
            return (self.disconnect.get(d) in PROFILING_CATEGORIES) and (d in self.secondary)
        if self.disconnect:
            return self.disconnect.get(d) in PROFILING_CATEGORIES
        if self.secondary:
            return d in self.secondary
        return d in BUILTIN_TRACKER_DOMAINS

    def category(self, hostname: str) -> str | None:
        d = get_etld1(hostname)
        if d in self.disconnect:
            return self.disconnect[d]
        if d in self.secondary or d in BUILTIN_TRACKER_DOMAINS:
            return "Advertising/Analytics (secondary list)"
        return None


def update_tracker_lists() -> None:
    """Download/refresh both tracker lists into ingestion/data/.
    Run this on your own machine (network required)."""
    import urllib.request

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[*] Downloading Disconnect list -> {DISCONNECT_PATH}")
    urllib.request.urlretrieve(DISCONNECT_URL, DISCONNECT_PATH)

    print(f"[*] Downloading Ghostery trackerdb -> {SECONDARY_PATH}")
    req = urllib.request.Request(SECONDARY_URL, headers={"User-Agent": "comp-square-research/1.0"})
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    # trackerdb.json structure:
    #   "patterns": {pattern_id: {"category": "...", "domains": [...], ...}, ...}
    #   and/or a top-level "domains": {domain: pattern_id} index.
    # Keep only domains whose pattern belongs to a tracking-related category;
    # if category info is unavailable, keep the domain (conservative for a
    # secondary list used in intersection mode).
    patterns = raw.get("patterns", {})
    domains: set[str] = set()

    def _pattern_category(pid) -> str | None:
        p = patterns.get(pid)
        return p.get("category") if isinstance(p, dict) else None

    for pid, p in patterns.items():
        if not isinstance(p, dict):
            continue
        cat = p.get("category")
        if cat is None or cat in GHOSTERY_PROFILING_CATEGORIES:
            for d in p.get("domains", []) or []:
                domains.add(get_etld1(d))

    for d, pid in (raw.get("domains", {}) or {}).items():
        cat = _pattern_category(pid)
        if cat is None or cat in GHOSTERY_PROFILING_CATEGORIES:
            domains.add(get_etld1(d))

    if not domains:
        raise RuntimeError(
            "Parsed 0 domains from trackerdb.json — its structure may have "
            "changed. Inspect the file and update update_tracker_lists()."
        )

    SECONDARY_PATH.write_text("\n".join(sorted(domains)), encoding="utf-8")
    print(f"[✓] {len(domains)} secondary tracker domains saved.")


# ─────────────────────────────────────────────────────────────────────────────
# Cookie parsing
# ─────────────────────────────────────────────────────────────────────────────
def _parse_set_cookie(header_value: str, request_host: str, started: str) -> dict:
    """Parse one Set-Cookie header value into a normalized record."""
    parts = [p.strip() for p in header_value.split(";")]
    name, _, value = parts[0].partition("=")
    attrs = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        attrs[k.strip().lower()] = v.strip()

    cookie_domain = attrs.get("domain", request_host).lstrip(".")

    lifetime_days = None
    if "max-age" in attrs:
        try:
            lifetime_days = int(attrs["max-age"]) / 86400.0
        except ValueError:
            pass
    elif "expires" in attrs:
        try:
            exp = parsedate_to_datetime(attrs["expires"])
            ref = datetime.fromisoformat(started.replace("Z", "+00:00")) if started else datetime.now(timezone.utc)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            lifetime_days = (exp - ref).total_seconds() / 86400.0
        except Exception:
            pass
    # No Max-Age/Expires => session cookie (lifetime 0)

    return {
        "name": name.strip(),
        "value_length": len(value),
        "cookie_domain": cookie_domain,
        "set_by_host": request_host,
        "set_at": started,
        "lifetime_days": round(lifetime_days, 1) if lifetime_days is not None else None,
        "session_cookie": lifetime_days is None,
        "http_only": "httponly" in attrs,
        "secure": "secure" in attrs,
        "same_site": attrs.get("samesite"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction
# ─────────────────────────────────────────────────────────────────────────────
def extract(har_path: str | Path,
            telemetry: str | Path | None = None,
            declared_domains: list[str] | None = None,
            declared_cookies: list[str] | None = None,
            tracker_db: TrackerDB | None = None) -> dict:
    """
    Parse a HAR (+ optional telemetry JSON) and return the behavioral
    evidence dict consumed by rag/scorer.py.

    declared_domains / declared_cookies: third-party domains and cookie names
    the site's written policy declares (from policy_reader / LLM extraction).
    When provided, a declared-vs-actual comparison is included using the
    Lalaine typology (neglect = observed but never declared).
    """
    har_path = Path(har_path)
    db = tracker_db or TrackerDB()

    har = json.loads(har_path.read_text(encoding="utf-8"))
    entries = har.get("log", {}).get("entries", [])

    # First-party domain: from telemetry meta if given, else first document request
    tele = None
    if telemetry:
        tele = json.loads(Path(telemetry).read_text(encoding="utf-8"))
    if tele and tele.get("meta", {}).get("etld1"):
        fp_etld1 = tele["meta"]["etld1"]
        scanned_url = tele["meta"].get("final_url") or tele["meta"].get("url")
    else:
        first_url = entries[0]["request"]["url"] if entries else ""
        fp_etld1 = get_etld1(urlparse(first_url).netloc)
        scanned_url = first_url

    # ── Walk HAR entries ────────────────────────────────────────────────────
    set_cookie_events: list[dict] = []
    contacted_domains: set[str] = set()
    tracker_requests: list[dict] = []

    for e in entries:
        url = e.get("request", {}).get("url", "")
        host = urlparse(url).netloc
        if not host:
            continue
        started = e.get("startedDateTime", "")
        third = is_third_party(host, fp_etld1)
        if third:
            contacted_domains.add(get_etld1(host))
            if db.is_profiling_tracker(host):
                tracker_requests.append({
                    "domain": get_etld1(host),
                    "url": url[:120],
                    "category": db.category(host),
                    "started": started,
                })

        for h in e.get("response", {}).get("headers", []):
            if h.get("name", "").lower() == "set-cookie":
                # HAR may fold multiple cookies into one header with newlines
                for one in h.get("value", "").split("\n"):
                    if one.strip():
                        rec = _parse_set_cookie(one, host, started)
                        rec["third_party"] = is_third_party(rec["cookie_domain"], fp_etld1)
                        set_cookie_events.append(rec)

    # ── Classify cookies (Trevisan rule) ────────────────────────────────────
    # No consent interaction is performed by the collector, therefore every
    # observed cookie is pre-consent by construction.
    profiling_cookies, other_third_party = [], []
    for c in set_cookie_events:
        c["is_tracker_domain"] = db.is_profiling_tracker(c["cookie_domain"]) or \
                                 db.is_profiling_tracker(c["set_by_host"])
        long_lived = (c["lifetime_days"] or 0) >= PROFILING_LIFETIME_DAYS
        c["profiling"] = bool(c["third_party"] and c["is_tracker_domain"] and long_lived)
        if c["profiling"]:
            profiling_cookies.append(c)
        elif c["third_party"]:
            other_third_party.append(c)

    # ── Telemetry extras (context cookies, fingerprinting, consent UI) ─────
    context_cookies, fingerprint_alarms, consent_ui_present = [], [], None
    if tele:
        ob = tele.get("observed_behavior", {})
        for c in ob.get("cookies", {}).get("all_cookies", []):
            dom = c.get("domain", "").lstrip(".")
            lifetime = None
            try:
                exp = float(c.get("expires", -1))
                if exp > 0:
                    cap = tele["meta"].get("captured_at")
                    ref = datetime.fromisoformat(cap) if cap else datetime.now(timezone.utc)
                    lifetime = (datetime.fromtimestamp(exp, tz=timezone.utc) - ref).total_seconds() / 86400.0
            except (TypeError, ValueError):
                pass
            context_cookies.append({
                "name": c.get("name"),
                "cookie_domain": dom,
                "third_party": bool(c.get("third_party")),
                "lifetime_days": round(lifetime, 1) if lifetime is not None else None,
                "is_tracker_domain": db.is_profiling_tracker(dom),
                "profiling": bool(c.get("third_party") and db.is_profiling_tracker(dom)
                                  and (lifetime or 0) >= PROFILING_LIFETIME_DAYS),
            })
        fingerprint_alarms = ob.get("fingerprinting_traps", {}).get("alarms", [])
        ui = tele.get("visual_evidence", {}).get("interactable_elements", {})
        consent_ui_present = (ui.get("consent_related_count", 0) > 0)

    # Merge: context cookies catch JS-set cookies missed by Set-Cookie headers
    har_names = {(c["name"], get_etld1(c["cookie_domain"])) for c in set_cookie_events}
    js_set_profiling = [c for c in context_cookies
                        if c["profiling"] and (c["name"], get_etld1(c["cookie_domain"])) not in har_names]

    # ── Declared vs actual (Lalaine typology) ───────────────────────────────
    declared_vs_actual = None
    if declared_domains is not None:
        declared = {get_etld1(d) for d in declared_domains}
        undeclared = sorted(contacted_domains - declared)
        declared_vs_actual = {
            "declared_third_party_domains": sorted(declared),
            "observed_third_party_domains": sorted(contacted_domains),
            "undeclared_domains": undeclared,
            # Lalaine: behaviour observed but never disclosed
            "discrepancy_type": "neglect" if undeclared else None,
        }
        if declared_cookies is not None:
            observed_names = {c["name"] for c in set_cookie_events} | \
                             {c["name"] for c in context_cookies if c.get("name")}
            undeclared_cookies = sorted(observed_names - set(declared_cookies))
            declared_vs_actual["undeclared_cookies"] = undeclared_cookies

    evidence = {
        "domain": fp_etld1,
        "scanned_url": scanned_url,
        "har_file": str(har_path),
        "tracker_list_mode": db.mode,          # intersection | single-list | builtin-fallback
        "consent_interaction": "none (clean-profile first visit — Trevisan et al. protocol)",
        "consent_ui_detected": consent_ui_present,
        "summary": {
            "total_requests": len(entries),
            "third_party_domains_contacted": len(contacted_domains),
            "tracker_requests": len(tracker_requests),
            "set_cookie_events": len(set_cookie_events),
            "pre_consent_profiling_cookies": len(profiling_cookies) + len(js_set_profiling),
            "fingerprinting_alarms": len(fingerprint_alarms),
        },
        "pre_consent_profiling_cookies": profiling_cookies,
        "js_set_profiling_cookies": js_set_profiling,
        "other_third_party_cookies": other_third_party,
        "third_party_domains": sorted(contacted_domains),
        "tracker_requests": tracker_requests[:50],
        "fingerprinting_alarms": fingerprint_alarms,
        "declared_vs_actual": declared_vs_actual,
    }
    return evidence


# ─────────────────────────────────────────────────────────────────────────────
# Prompt-context rendering (format from RAG_Pipeline_Architecture.md §3.3)
# ─────────────────────────────────────────────────────────────────────────────
def to_prompt_context(evidence: dict, max_items: int = 15) -> str:
    """Render the evidence dict as the text block injected into LLM prompts."""
    lines = [
        f"BEHAVIORAL EVIDENCE — {evidence['domain']}",
        f"HAR file: {Path(evidence['har_file']).name}",
        f"Consent interaction performed: {evidence['consent_interaction']}",
        f"Consent UI detected on page: {evidence['consent_ui_detected']}",
        f"Tracker classification mode: {evidence['tracker_list_mode']}",
        "",
    ]

    prof = evidence["pre_consent_profiling_cookies"] + evidence["js_set_profiling_cookies"]
    if prof:
        lines.append(f"Potential pre-consent profiling cookies ({len(prof)}) "
                     f"[third-party + tracker-listed + lifetime >= {PROFILING_LIFETIME_DAYS}d]:")
        for c in prof[:max_items]:
            life = f"{c['lifetime_days']:.0f} days" if c.get("lifetime_days") else "session"
            lines.append(f"  - Cookie '{c['name']}' ({c['cookie_domain']}). Duration: {life}.")
        if len(prof) > max_items:
            lines.append(f"  ... and {len(prof) - max_items} more.")
    else:
        lines.append("No profiling cookies detected before consent.")
    lines.append("")

    trk = evidence["tracker_requests"]
    if trk:
        uniq = sorted({t["domain"] for t in trk})
        lines.append(f"Tracker-listed domains contacted ({len(uniq)}) — requests fired "
                     f"even if no cookie was set (possible cookieless/consent-mode pings):")
        for d in uniq[:max_items]:
            lines.append(f"  - {d}")
        lines.append("")

    tp = evidence["third_party_domains"]
    lines.append(f"Third-party domains contacted: {len(tp)}")
    for d in tp[:max_items]:
        lines.append(f"  - {d}")
    if len(tp) > max_items:
        lines.append(f"  ... and {len(tp) - max_items} more.")
    lines.append("")

    if evidence["fingerprinting_alarms"]:
        lines.append(f"Fingerprinting API calls observed ({len(evidence['fingerprinting_alarms'])}):")
        for a in evidence["fingerprinting_alarms"][:max_items]:
            lines.append(f"  - {a}")
        lines.append("")

    dva = evidence.get("declared_vs_actual")
    if dva:
        lines.append(f"Declared vs actual third parties: "
                     f"{len(dva['declared_third_party_domains'])} declared, "
                     f"{len(dva['observed_third_party_domains'])} observed, "
                     f"{len(dva['undeclared_domains'])} undeclared.")
        if dva["undeclared_domains"]:
            lines.append(f"Undeclared (discrepancy type: {dva['discrepancy_type']}):")
            for d in dva["undeclared_domains"][:max_items]:
                lines.append(f"  - {d}")

    lines.append("")
    lines.append("NOTE: findings are POTENTIAL violations pending legal assessment "
                 "(conservative classification; false negatives preferred).")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Extract behavioral evidence from HAR + telemetry.")
    ap.add_argument("har", nargs="?", help="Path to .har file")
    ap.add_argument("--telemetry", help="Path to matching *_telemetry.json")
    ap.add_argument("--json", help="Write evidence dict to this path")
    ap.add_argument("--update-lists", action="store_true",
                    help="Download/refresh tracker lists into ingestion/data/")
    args = ap.parse_args()

    if args.update_lists:
        update_tracker_lists()
        sys.exit(0)

    if not args.har:
        ap.error("har path required (or use --update-lists)")

    ev = extract(args.har, telemetry=args.telemetry)
    print(to_prompt_context(ev))

    if args.json:
        Path(args.json).write_text(json.dumps(ev, indent=2), encoding="utf-8")
        print(f"\n[✓] Evidence dict written to {args.json}")
