"""
Advanced Telemetry Collector - Phase 2 of LLM-Driven Privacy Compliance Framework
Captures: Network Requests (HAR), Cookies, Console Logs, DOM Content, Security Headers,
          SSL Details, Fingerprinting Traps, UI Elements, Visual Evidence
Author: Aaron Joseph Jean - 25233118
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ── FINGERPRINTING TRAP SCRIPT ────────────────────────────────────────────────
# Injected before page load to intercept privacy-sensitive browser API access
FINGERPRINT_TRAP_SCRIPT = """
(function() {
    function alarm(api) {
        console.warn('COMPLIANCE_ALARM: Access to ' + api + ' detected at ' + new Date().toISOString());
    }

    // Geolocation trap
    const origGeo = navigator.geolocation.getCurrentPosition.bind(navigator.geolocation);
    navigator.geolocation.getCurrentPosition = function(...args) {
        alarm('navigator.geolocation.getCurrentPosition');
        return origGeo(...args);
    };
    const origGeoWatch = navigator.geolocation.watchPosition.bind(navigator.geolocation);
    navigator.geolocation.watchPosition = function(...args) {
        alarm('navigator.geolocation.watchPosition');
        return origGeoWatch(...args);
    };

    // MediaDevices trap
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const origMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = function(...args) {
            alarm('navigator.mediaDevices.getUserMedia');
            return origMedia(...args);
        };
    }

    // Clipboard trap
    if (navigator.clipboard) {
        const origRead = navigator.clipboard.read ? navigator.clipboard.read.bind(navigator.clipboard) : null;
        const origReadText = navigator.clipboard.readText ? navigator.clipboard.readText.bind(navigator.clipboard) : null;
        if (origRead) navigator.clipboard.read = function(...args) {
            alarm('navigator.clipboard.read');
            return origRead(...args);
        };
        if (origReadText) navigator.clipboard.readText = function(...args) {
            alarm('navigator.clipboard.readText');
            return origReadText(...args);
        };
    }

    // Canvas fingerprinting trap
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
        alarm('HTMLCanvasElement.prototype.toDataURL (canvas fingerprinting)');
        return origToDataURL.apply(this, args);
    };

    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(...args) {
        if (args[0] === 'webgl' || args[0] === 'webgl2') {
            alarm('HTMLCanvasElement.getContext(' + args[0] + ') (WebGL fingerprinting)');
        }
        return origGetContext.apply(this, args);
    };
})();
"""

# ── UI ELEMENT EXTRACTION SCRIPT ─────────────────────────────────────────────
UI_ELEMENT_SCRIPT = """
() => {
    const elements = document.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]');
    const results = [];
    elements.forEach(el => {
        const style = window.getComputedStyle(el);
        results.push({
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().substring(0, 100),
            href: el.href || null,
            visible: el.offsetParent !== null,
            backgroundColor: style.backgroundColor,
            role: el.getAttribute('role') || null,
            type: el.getAttribute('type') || null
        });
    });
    return results;
}
"""


async def collect_telemetry(url: str, output_dir: str = "telemetry_output"):
    """
    Collects full website telemetry for LLM-driven privacy compliance analysis.

    Args:
        url: The target website URL
        output_dir: Directory to save all captured telemetry

    Returns:
        dict: Structured LLM-ready telemetry payload
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain      = urlparse(url).netloc or url.split("/")[2]
    first_party = domain.lstrip("www.")

    # Raw capture buckets
    raw_requests      = []
    raw_responses     = {}
    console_logs      = []
    compliance_alarms = []

    print(f"\n{'='*60}")
    print(f"  TELEMETRY COLLECTOR — LLM Privacy Compliance Framework")
    print(f"{'='*60}")
    print(f"  Target  : {url}")
    print(f"  Domain  : {domain}")
    print(f"  Output  : {output_dir}/")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ── 1. CLEAN ROOM CONTEXT ─────────────────────────────────────────
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080},
            record_har_path=str(output_path / f"{domain}_{timestamp}.har"),
            java_script_enabled=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # ── 2. FINGERPRINTING & API TRAPS ─────────────────────────────────
        print("[*] Injecting fingerprinting traps ...")
        await page.add_init_script(FINGERPRINT_TRAP_SCRIPT)

        # ── 3. CONSOLE LOG CAPTURE ────────────────────────────────────────
        def handle_console(msg):
            entry = {"type": msg.type, "text": msg.text, "location": msg.location}
            console_logs.append(entry)
            if "COMPLIANCE_ALARM" in msg.text:
                compliance_alarms.append(msg.text)
                print(f"  ⚠  ALARM: {msg.text}")

        page.on("console", handle_console)

        # ── 4. NETWORK REQUEST CAPTURE ────────────────────────────────────
        def handle_request(request):
            try:
                post_data = request.post_data
            except Exception:
                post_data = "<binary/compressed data>"

            req_domain    = urlparse(request.url).netloc
            is_third_party = first_party not in req_domain

            raw_requests.append({
                "url":           request.url,
                "method":        request.method,
                "resource_type": request.resource_type,
                "headers":       dict(request.headers),
                "post_data":     post_data,
                "third_party":   is_third_party,
                "domain":        req_domain
            })

        # ── 5. ADVANCED RESPONSE & SSL CAPTURE ───────────────────────────
        async def handle_response(response):
            if response.request.resource_type != "document":
                return
            try:
                headers = dict(response.headers)

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
                    ssl_info = {"error": "Could not retrieve SSL details"}

                security_header_keys = [
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
                    "cross-origin-resource-policy"
                ]

                raw_responses[response.url] = {
                    "status":           response.status,
                    "security_headers": {k: headers[k] for k in security_header_keys if k in headers},
                    "missing_headers":  [k for k in security_header_keys if k not in headers],
                    "ssl":              ssl_info
                }
            except Exception as e:
                raw_responses[response.url] = {"error": str(e)}

        page.on("request", handle_request)
        page.on("response", handle_response)

        # ── 6. NAVIGATE ───────────────────────────────────────────────────
        print(f"[*] Navigating to {url} ...")
        try:
            # Try full networkidle first — some sites never reach it so we fall back
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            print("[!] networkidle timed out — falling back to domcontentloaded ...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[!] Navigation failed: {e}")
                await browser.close()
                return {}
        await asyncio.sleep(3)
        print("[*] Page fully loaded.\n")

        # ── 7. COOKIES ────────────────────────────────────────────────────
        print("[*] Capturing cookies ...")
        raw_cookies = await context.cookies()
        cookies = []
        for c in raw_cookies:
            c_domain      = c["domain"].lstrip(".")
            is_third_party = first_party not in c_domain
            cookies.append({
                "name":        c["name"],
                "domain":      c["domain"],
                "path":        c["path"],
                "secure":      c["secure"],
                "httpOnly":    c["httpOnly"],
                "sameSite":    c.get("sameSite", "None"),
                "expires":     c.get("expires", -1),
                "third_party": is_third_party
            })

        # ── 8. FULL PAGE SCREENSHOT ───────────────────────────────────────
        print("[*] Capturing full-page screenshot ...")
        screenshot_path = output_path / f"{domain}_{timestamp}_screenshot.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)

        # ── 9. UI ELEMENT EXTRACTION ──────────────────────────────────────
        print("[*] Extracting interactable UI elements ...")
        try:
            ui_elements = await page.evaluate(UI_ELEMENT_SCRIPT)
        except Exception as e:
            ui_elements = [{"error": str(e)}]

        # ── 10. DOM CAPTURE & OPTIMISATION ───────────────────────────────
        print("[*] Capturing and cleaning DOM for LLM ...")
        raw_dom = await page.content()
        soup = BeautifulSoup(raw_dom, "html.parser")

        for tag in soup(["style", "script", "svg", "meta", "noscript", "link", "iframe"]):
            tag.decompose()
        for element in soup.find_all(string=lambda text: text and text.strip().startswith("<!")):
            element.extract()

        clean_dom = str(soup)
        dom_file  = output_path / f"{domain}_{timestamp}_dom.html"
        dom_file.write_text(clean_dom, encoding="utf-8")

        await context.close()
        await browser.close()

    # ── 11. BUILD LLM-FRIENDLY PAYLOAD ───────────────────────────────────────
    main_response      = next(iter(raw_responses.values()), {})
    third_party_domains = list({
        r["domain"] for r in raw_requests if r.get("third_party") and r["domain"]
    })
    third_party_cookies = [c for c in cookies if c.get("third_party")]

    telemetry = {
        "meta": {
            "url":         url,
            "domain":      domain,
            "captured_at": timestamp,
            "tool":        "Privacy Compliance Telemetry Collector v2.0"
        },

        # Section 1 — Infrastructure Security
        "infrastructure_security": {
            "https_enforced":   url.startswith("https://"),
            "ssl":              main_response.get("ssl", {}),
            "security_headers": main_response.get("security_headers", {}),
            "missing_headers":  main_response.get("missing_headers", [])
        },

        # Section 2 — Observed Behaviour
        "observed_behavior": {
            "network_summary": {
                "total_requests":        len(raw_requests),
                "third_party_requests":  sum(1 for r in raw_requests if r.get("third_party")),
                "third_party_domains":   third_party_domains,
                "post_requests":         [r for r in raw_requests if r["method"] == "POST"]
            },
            "cookies": {
                "total":              len(cookies),
                "third_party_count":  len(third_party_cookies),
                "third_party_cookies": third_party_cookies,
                "all_cookies":        cookies
            },
            "fingerprinting_traps": {
                "alarms_triggered": len(compliance_alarms),
                "alarms":           compliance_alarms
            },
            "console_logs": console_logs,
            "all_requests": raw_requests
        },

        # Section 3 — Visual Evidence
        "visual_evidence": {
            "screenshot_path": str(screenshot_path),
            "dom_file":        str(dom_file),
            "interactable_elements": {
                "total":    len(ui_elements),
                "elements": ui_elements
            }
        }
    }

    # ── 12. SAVE JSON ─────────────────────────────────────────────────────────
    output_file = output_path / f"{domain}_{timestamp}_telemetry.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2, default=str)

    # ── 13. PRINT SUMMARY ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"           TELEMETRY COLLECTION SUMMARY")
    print(f"{'='*60}")
    print(f"  Total Requests         : {len(raw_requests)}")
    print(f"  Third-Party Requests   : {sum(1 for r in raw_requests if r.get('third_party'))}")
    print(f"  Third-Party Domains    : {len(third_party_domains)}")
    print(f"  Cookies (Total)        : {len(cookies)}")
    print(f"  Third-Party Cookies    : {len(third_party_cookies)}")
    print(f"  Console Logs           : {len(console_logs)}")
    print(f"  Compliance Alarms      : {len(compliance_alarms)}")
    print(f"  Security Headers Found : {len(main_response.get('security_headers', {}))}")
    print(f"  Missing Headers        : {len(main_response.get('missing_headers', []))}")
    print(f"  UI Elements Found      : {len(ui_elements)}")
    print(f"{'='*60}")

    if main_response.get("missing_headers"):
        print(f"\n  ⚠  Missing Security Headers:")
        for h in main_response["missing_headers"]:
            print(f"     - {h}")

    if third_party_domains:
        print(f"\n  Third-Party Domains Detected ({len(third_party_domains)}):")
        for d in third_party_domains[:10]:
            print(f"     - {d}")

    if compliance_alarms:
        print(f"\n  🚨 Fingerprinting / API Alarms Triggered:")
        for a in compliance_alarms:
            print(f"     - {a}")

    print(f"\n  Output Files Saved:")
    print(f"     - {output_file.name}         (main telemetry)")
    print(f"     - {dom_file.name}            (clean DOM)")
    print(f"     - {screenshot_path.name}     (visual evidence)")
    print(f"     - {domain}_{timestamp}.har   (full HAR)")
    print(f"\n[✓] Done.\n")

    return telemetry


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://bbc.com"
    asyncio.run(collect_telemetry(target_url))