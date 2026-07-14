"""
Advanced Telemetry Collector v3.0
LLM-Driven Privacy Compliance Framework — Phase 2
Author: Aaron Joseph Jean — 25233118

Refinements implemented:
  1.  eTLD+1 third-party detection (requests + cookies)
  2.  Security headers/SSL from final page URL
  3.  Extended fingerprinting traps (AudioContext, WebRTC, Battery, fonts)
  4.  Non-document response headers (scripts / XHR / fetch) with cap
  5.  Meta tags + policy links extracted before DOM cleaning
  6.  Handler robustness (try/except) + configurable caps
  7.  ISO timestamps throughout; no reliance on default=str for key fields
  8.  policy_links list + policy_cross_check placeholder section
  9.  Consent-related UI element tagging
  10. Configurable timeouts / wait_until / post_load_delay
  11. Multiple URL batch support (CLI or list)
  12. Unique HAR path per context / run
"""

import json
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — lightweight eTLD+1 without external library  (Refinement 1)
# ─────────────────────────────────────────────────────────────────────────────
MULTI_TLDS = {
    "co.uk", "org.uk", "me.uk", "net.uk", "ac.uk",
    "co.in", "org.in", "net.in", "ac.in",
    "co.au", "com.au", "net.au", "org.au",
    "co.nz", "com.nz", "co.za", "com.br",
    "co.jp", "ne.jp", "or.jp", "ac.jp",
    # private public-suffix registries (kept in sync with har_extractor.py)
    "eu.com", "us.com", "uk.com", "de.com", "gb.com", "cn.com",
    "jpn.com", "za.com", "br.com", "sa.com", "se.com", "ru.com",
    "uk.net", "gb.net", "se.net",
}

def get_etld1(hostname: str) -> str:
    """Return the registrable domain (eTLD+1) for a hostname."""
    hostname = hostname.lower().lstrip(".")
    parts = hostname.split(".")
    if len(parts) <= 1:
        return hostname
    two_part = ".".join(parts[-2:])
    if two_part in MULTI_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return two_part

def is_third_party(request_hostname: str, first_party_etld1: str) -> bool:
    """True if request_hostname belongs to a different registrable domain."""
    if not request_hostname:
        return False
    return get_etld1(request_hostname) != first_party_etld1


# ─────────────────────────────────────────────────────────────────────────────
# FINGERPRINTING TRAP SCRIPT  (Refinements 2 + 3)
# ─────────────────────────────────────────────────────────────────────────────
FINGERPRINT_TRAP_SCRIPT = """
(function () {
    function alarm(api) {
        console.warn('COMPLIANCE_ALARM: ' + api + ' accessed at ' + new Date().toISOString());
    }

    // ── Geolocation ──────────────────────────────────────────────────────
    try {
        const g = navigator.geolocation;
        ['getCurrentPosition','watchPosition'].forEach(fn => {
            const orig = g[fn].bind(g);
            g[fn] = function (...a) { alarm('navigator.geolocation.' + fn); return orig(...a); };
        });
    } catch(e) {}

    // ── MediaDevices ─────────────────────────────────────────────────────
    try {
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = function (...a) {
                alarm('navigator.mediaDevices.getUserMedia'); return orig(...a);
            };
        }
    } catch(e) {}

    // ── Clipboard ────────────────────────────────────────────────────────
    try {
        if (navigator.clipboard) {
            ['read','readText'].forEach(fn => {
                if (navigator.clipboard[fn]) {
                    const orig = navigator.clipboard[fn].bind(navigator.clipboard);
                    navigator.clipboard[fn] = function (...a) {
                        alarm('navigator.clipboard.' + fn); return orig(...a);
                    };
                }
            });
        }
    } catch(e) {}

    // ── Canvas fingerprinting ────────────────────────────────────────────
    try {
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function (...a) {
            alarm('HTMLCanvasElement.toDataURL (canvas fingerprinting)');
            return origToDataURL.apply(this, a);
        };
        const origGetCtx = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (...a) {
            if (a[0] === 'webgl' || a[0] === 'webgl2')
                alarm('HTMLCanvasElement.getContext(' + a[0] + ') (WebGL fingerprinting)');
            return origGetCtx.apply(this, a);
        };
    } catch(e) {}

    // ── AudioContext fingerprinting ───────────────────────────────────────
    try {
        ['AudioContext','webkitAudioContext'].forEach(name => {
            if (window[name]) {
                const Orig = window[name];
                window[name] = function (...a) {
                    alarm(name + ' instantiated (audio fingerprinting)');
                    return new Orig(...a);
                };
                Object.setPrototypeOf(window[name], Orig);
            }
        });
    } catch(e) {}

    // ── WebRTC ───────────────────────────────────────────────────────────
    try {
        if (window.RTCPeerConnection) {
            const Orig = window.RTCPeerConnection;
            window.RTCPeerConnection = function (...a) {
                alarm('RTCPeerConnection created (WebRTC / IP leak risk)');
                return new Orig(...a);
            };
            Object.setPrototypeOf(window.RTCPeerConnection, Orig);
        }
    } catch(e) {}

    // ── Battery API ───────────────────────────────────────────────────────
    try {
        if (navigator.getBattery) {
            const origBat = navigator.getBattery.bind(navigator);
            navigator.getBattery = function (...a) {
                alarm('navigator.getBattery (battery fingerprinting)');
                return origBat(...a);
            };
        }
    } catch(e) {}

    // ── Font enumeration ─────────────────────────────────────────────────
    try {
        if (document.fonts && document.fonts.check) {
            const origCheck = document.fonts.check.bind(document.fonts);
            document.fonts.check = function (...a) {
                alarm('document.fonts.check (font fingerprinting)');
                return origCheck(...a);
            };
        }
    } catch(e) {}
})();
"""

# ─────────────────────────────────────────────────────────────────────────────
# UI ELEMENT EXTRACTION  (Refinement 9 — consent tagging)
# ─────────────────────────────────────────────────────────────────────────────
UI_ELEMENT_SCRIPT = """
() => {
    const CONSENT_TOKENS = ['accept','reject','cookie','privacy','opt-out','opt out',
                            'settings','preferences','agree','decline','consent','manage'];
    const els = document.querySelectorAll(
        'button, a, [role="button"], input[type="submit"], input[type="button"]'
    );
    const results = [];
    els.forEach(el => {
        const style  = window.getComputedStyle(el);
        const rawText = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
        const lc     = rawText.toLowerCase();
        results.push({
            tag:                    el.tagName.toLowerCase(),
            text:                   rawText.substring(0, 100),
            href:                   el.href || null,
            visible:                el.offsetParent !== null,
            backgroundColor:        style.backgroundColor,
            role:                   el.getAttribute('role') || null,
            type:                   el.getAttribute('type') || null,
            likely_consent_related: CONSENT_TOKENS.some(t => lc.includes(t))
        });
    });
    return results;
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# SECURITY HEADER KEYS
# ─────────────────────────────────────────────────────────────────────────────
SECURITY_HEADER_KEYS = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "reporting-endpoints",
    "x-xss-protection",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
]

POLICY_KEYWORDS = ["privacy", "cookie", "terms", "policy", "legal", "gdpr", "data-protection"]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN COLLECTOR
# ─────────────────────────────────────────────────────────────────────────────
async def collect_telemetry(
    url: str,
    output_dir: str  = "telemetry_output",
    timeout: int     = 30000,
    wait_until: str  = "networkidle",
    post_load_delay: int = 3,
    max_requests: int    = 2000,
    max_console: int     = 500,
    max_non_doc: int     = 100,
) -> dict:
    """
    Collect full website telemetry for LLM-driven privacy compliance analysis.

    Args:
        url             : Target URL
        output_dir      : Folder for all output files
        timeout         : Navigation timeout in ms  (Refinement 10)
        wait_until      : Playwright wait strategy  (Refinement 10)
        post_load_delay : Seconds to wait after load (Refinement 10)
        max_requests    : Cap on stored requests     (Refinement 6)
        max_console     : Cap on console log entries (Refinement 6)
        max_non_doc     : Cap on non-document responses (Refinement 4)
    Returns:
        Structured telemetry dict
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Refinement 7 — ISO timestamp
    captured_at   = datetime.now(timezone.utc).isoformat()
    ts_safe       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    parsed        = urlparse(url)
    domain        = parsed.netloc or url.split("/")[2]
    fp_etld1      = get_etld1(domain)                    # Refinement 1

    # Capture buckets
    raw_requests      = []
    raw_responses     = {}       # url → response info
    non_doc_responses = []       # Refinement 4
    console_logs      = []
    compliance_alarms = []
    requests_capped   = False
    console_capped    = False

    print(f"\n{'='*62}")
    print(f"  TELEMETRY COLLECTOR v3.0 — Privacy Compliance Framework")
    print(f"{'='*62}")
    print(f"  Target     : {url}")
    print(f"  Domain     : {domain}  (eTLD+1: {fp_etld1})")
    print(f"  Output     : {output_dir}/")
    print(f"  Captured   : {captured_at}")
    print(f"{'='*62}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ── Context — clean room  (Refinement 10 + 12) ───────────────────
        har_path = output_path / f"{domain}_{ts_safe}.har"
        context  = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080},
            record_har_path=str(har_path),
            java_script_enabled=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # ── Fingerprinting traps  (Refinement 3) ─────────────────────────
        print("[*] Injecting fingerprinting traps ...")
        await page.add_init_script(FINGERPRINT_TRAP_SCRIPT)

        # ── Console handler  (Refinement 6) ──────────────────────────────
        def handle_console(msg):
            nonlocal console_capped
            try:
                entry = {"type": msg.type, "text": msg.text, "location": msg.location}
                if len(console_logs) < max_console:
                    console_logs.append(entry)
                else:
                    console_capped = True
                if "COMPLIANCE_ALARM" in msg.text:
                    compliance_alarms.append(msg.text)
                    print(f"  ⚠  ALARM: {msg.text}")
            except Exception as e:
                console_logs.append({"error": str(e)})

        page.on("console", handle_console)

        # ── Request handler  (Refinements 1 + 6) ─────────────────────────
        def handle_request(request):
            nonlocal requests_capped
            try:
                if len(raw_requests) >= max_requests:
                    requests_capped = True
                    return
                try:
                    post_data = request.post_data
                except Exception:
                    post_data = "<binary/compressed>"

                req_domain = urlparse(request.url).netloc
                raw_requests.append({
                    "url":           request.url,
                    "method":        request.method,
                    "resource_type": request.resource_type,
                    "headers":       dict(request.headers),
                    "post_data":     post_data,
                    "third_party":   is_third_party(req_domain, fp_etld1),
                    "domain":        req_domain
                })
            except Exception as e:
                raw_requests.append({"url": getattr(request, "url", "unknown"), "error": str(e)})

        # ── Response handler  (Refinements 2 + 4 + 6) ────────────────────
        async def handle_response(response):
            try:
                rtype   = response.request.resource_type
                headers = dict(response.headers)

                if rtype == "document":
                    ssl_info = {}
                    try:
                        sec = await response.security_details()
                        if sec:
                            ssl_info = {
                                "protocol":     sec.get("protocol", "unknown"),
                                "cipher":       sec.get("cipher", "unknown"),
                                "subject_name": sec.get("subjectName", ""),
                                "issuer":       sec.get("issuer", ""),
                                "valid_from":   sec.get("validFrom", ""),
                                "valid_to":     sec.get("validTo", "")
                            }
                    except Exception:
                        ssl_info = {"error": "SSL details unavailable"}

                    raw_responses[response.url] = {
                        "status":           response.status,
                        "resource_type":    rtype,
                        "security_headers": {k: headers[k] for k in SECURITY_HEADER_KEYS if k in headers},
                        "missing_headers":  [k for k in SECURITY_HEADER_KEYS if k not in headers],
                        "ssl":              ssl_info
                    }

                # Refinement 4 — capture script/xhr/fetch responses (capped)
                elif rtype in ("script", "xhr", "fetch") and len(non_doc_responses) < max_non_doc:
                    req_domain = urlparse(response.url).netloc
                    set_cookie = headers.get("set-cookie", None)
                    non_doc_responses.append({
                        "url":          response.url,
                        "status":       response.status,
                        "resource_type": rtype,
                        "third_party":  is_third_party(req_domain, fp_etld1),
                        "domain":       req_domain,
                        "set_cookie":   set_cookie,
                        "headers":      {k: headers[k] for k in SECURITY_HEADER_KEYS if k in headers}
                    })
            except Exception as e:
                raw_responses[getattr(response, "url", "unknown")] = {"error": str(e)}

        page.on("request", handle_request)
        page.on("response", handle_response)

        # ── Navigate  (Refinement 10) ─────────────────────────────────────
        print(f"[*] Navigating to {url} ...")
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception:
            print(f"[!] '{wait_until}' timed out — falling back to domcontentloaded ...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            except Exception as e:
                print(f"[!] Navigation failed entirely: {e}")
                await browser.close()
                return {}

        await asyncio.sleep(post_load_delay)
        final_url = page.url                             # Refinement 2
        print(f"[*] Final URL : {final_url}\n")

        # ── Cookies ───────────────────────────────────────────────────────
        print("[*] Capturing cookies ...")
        raw_cookies = await context.cookies()
        cookies = []
        for c in raw_cookies:
            c_domain = c["domain"].lstrip(".")
            cookies.append({
                "name":        c["name"],
                "domain":      c["domain"],
                "path":        c["path"],
                "secure":      c["secure"],
                "httpOnly":    c["httpOnly"],
                "sameSite":    c.get("sameSite", "None"),
                "expires":     c.get("expires", -1),
                "third_party": is_third_party(c_domain, fp_etld1)   # Refinement 1
            })

        # ── Screenshot ────────────────────────────────────────────────────
        print("[*] Capturing full-page screenshot ...")
        screenshot_path = output_path / f"{domain}_{ts_safe}_screenshot.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)

        # ── UI Elements  (Refinement 9) ───────────────────────────────────
        print("[*] Extracting UI elements ...")
        try:
            ui_elements = await page.evaluate(UI_ELEMENT_SCRIPT)
        except Exception as e:
            ui_elements = [{"error": str(e)}]

        # ── DOM — extract meta/links BEFORE cleaning  (Refinements 5 + 8) ─
        print("[*] Extracting meta tags and policy links ...")
        raw_dom = await page.content()
        soup    = BeautifulSoup(raw_dom, "html.parser")

        # Extract meta tags
        meta_tags = []
        for m in soup.find_all("meta"):
            name    = m.get("name") or m.get("property") or m.get("http-equiv", "")
            content = m.get("content", "")
            if name and content:
                meta_tags.append({"name": name, "content": content})

        # Extract policy-related links  (Refinement 8)
        policy_links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if any(kw in href.lower() or kw in text.lower() for kw in POLICY_KEYWORDS):
                policy_links.append({"href": href, "text": text[:120]})

        # Clean DOM for LLM  (Refinement 5)
        for tag in soup(["style", "script", "svg", "noscript", "link", "iframe"]):
            tag.decompose()
        # Keep <meta> in DOM so referrer-policy meta tags are visible
        clean_dom = str(soup)

        dom_file = output_path / f"{domain}_{ts_safe}_dom.html"
        dom_file.write_text(clean_dom, encoding="utf-8")

        await context.close()
        await browser.close()

    # ── Pick main response from final URL  (Refinement 2) ────────────────────
    main_response        = raw_responses.get(final_url)
    main_response_source = "final_url"
    if not main_response:
        main_response        = next(iter(raw_responses.values()), {})
        main_response_source = "fallback_first_document"

    # ── Aggregate ─────────────────────────────────────────────────────────────
    third_party_domains = sorted({
        r["domain"] for r in raw_requests
        if r.get("third_party") and r.get("domain")
    })
    third_party_cookies = [c for c in cookies if c.get("third_party")]
    consent_elements    = [e for e in ui_elements if e.get("likely_consent_related")]

    # ── Build LLM payload ─────────────────────────────────────────────────────
    telemetry = {

        # ── Meta ─────────────────────────────────────────────────────────
        "meta": {
            "url":              url,
            "final_url":        final_url,
            "domain":           domain,
            "etld1":            fp_etld1,
            "captured_at":      captured_at,           # Refinement 7 — ISO
            "tool":             "Privacy Compliance Telemetry Collector v3.0",
            "requests_capped":  requests_capped,
            "console_capped":   console_capped,
            "main_response_source": main_response_source
        },

        # ── Section 1: Infrastructure Security ───────────────────────────
        "infrastructure_security": {
            "https_enforced":   final_url.startswith("https://"),
            "ssl":              main_response.get("ssl", {}),
            "security_headers": main_response.get("security_headers", {}),
            "missing_headers":  main_response.get("missing_headers", [])
        },

        # ── Section 2: Observed Behaviour ────────────────────────────────
        "observed_behavior": {
            "network_summary": {
                "total_requests":       len(raw_requests),
                "third_party_requests": sum(1 for r in raw_requests if r.get("third_party")),
                "third_party_domains":  third_party_domains,
                "post_requests":        [r for r in raw_requests if r.get("method") == "POST"]
            },
            "non_document_responses":  non_doc_responses,   # Refinement 4
            "cookies": {
                "total":               len(cookies),
                "third_party_count":   len(third_party_cookies),
                "third_party_cookies": third_party_cookies,
                "all_cookies":         cookies
            },
            "fingerprinting_traps": {
                "alarms_triggered": len(compliance_alarms),
                "alarms":           compliance_alarms
            },
            "console_logs": console_logs,
            "all_requests": raw_requests
        },

        # ── Section 3: Visual Evidence ────────────────────────────────────
        "visual_evidence": {
            "screenshot_path": str(screenshot_path),
            "dom_file":        str(dom_file),
            "interactable_elements": {
                "total":                  len(ui_elements),
                "consent_related_count":  len(consent_elements),
                "consent_elements":       consent_elements,
                "all_elements":           ui_elements
            }
        },

        # ── Section 4: Declared vs Observed  (Refinements 5 + 8) ─────────
        "declared_vs_observed": {
            "meta_tags":    meta_tags,
            "policy_links": policy_links,
            "policy_cross_check": {
                "policy_url":              None,   # Filled in Phase 1 (LLM policy extraction)
                "declared_third_parties":  None,
                "declared_cookies":        None,
                "declared_fingerprinting": None,
                "declared_data_retention": None
            }
        }
    }

    # ── Save JSON ─────────────────────────────────────────────────────────────
    output_file = output_path / f"{domain}_{ts_safe}_telemetry.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2, default=str)

    # ── Print summary ─────────────────────────────────────────────────────────
    sec_h = main_response.get("security_headers", {})
    mis_h = main_response.get("missing_headers", [])
    print(f"\n{'='*62}")
    print(f"           TELEMETRY SUMMARY")
    print(f"{'='*62}")
    print(f"  Final URL              : {final_url}")
    print(f"  Total Requests         : {len(raw_requests)}" + (" [CAPPED]" if requests_capped else ""))
    print(f"  Third-Party Requests   : {sum(1 for r in raw_requests if r.get('third_party'))}")
    print(f"  Third-Party Domains    : {len(third_party_domains)}")
    print(f"  Non-Doc Responses      : {len(non_doc_responses)}")
    print(f"  Cookies (Total)        : {len(cookies)}")
    print(f"  Third-Party Cookies    : {len(third_party_cookies)}")
    print(f"  Console Logs           : {len(console_logs)}" + (" [CAPPED]" if console_capped else ""))
    print(f"  Compliance Alarms      : {len(compliance_alarms)}")
    print(f"  Security Headers Found : {len(sec_h)}")
    print(f"  Missing Headers        : {len(mis_h)}")
    print(f"  UI Elements            : {len(ui_elements)}")
    print(f"  Consent Elements       : {len(consent_elements)}")
    print(f"  Meta Tags              : {len(meta_tags)}")
    print(f"  Policy Links Found     : {len(policy_links)}")
    print(f"{'='*62}")

    if mis_h:
        print(f"\n  ⚠  Missing Security Headers:")
        for h in mis_h:
            print(f"     - {h}")

    if third_party_domains:
        print(f"\n  Third-Party Domains ({len(third_party_domains)}):")
        for d in third_party_domains[:10]:
            print(f"     - {d}")
        if len(third_party_domains) > 10:
            print(f"     ... and {len(third_party_domains) - 10} more (see JSON)")

    if compliance_alarms:
        print(f"\n  🚨 Fingerprinting Alarms:")
        for a in compliance_alarms:
            print(f"     - {a}")

    if policy_links:
        print(f"\n  Policy Links Found:")
        for pl in policy_links[:5]:
            print(f"     - [{pl['text'][:40]}] {pl['href'][:60]}")

    print(f"\n  Output Files:")
    print(f"     - {output_file.name}")
    print(f"     - {dom_file.name}")
    print(f"     - {screenshot_path.name}")
    print(f"     - {har_path.name}")
    print(f"\n[✓] Done — {domain}\n")

    return telemetry


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — single or batch  (Refinements 11 + 12)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    urls = sys.argv[1:] if len(sys.argv) > 1 else ["https://bbc.com"]

    async def run_batch(urls):
        for url in urls:
            await collect_telemetry(url)

    asyncio.run(run_batch(urls))