"""
Telemetry Collector - Phase 2 of LLM-Driven Privacy Compliance Framework
Captures: Network Requests (HAR), Cookies, Console Logs, DOM Content, Security Headers
Author: Aaron Joseph Jean - 25233118
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright


async def collect_telemetry(url: str, output_dir: str = "telemetry_output"):
    """
    Collects full website telemetry for privacy compliance analysis.
    
    Args:
        url: The target website URL
        output_dir: Directory to save captured telemetry
    
    Returns:
        dict: All collected telemetry data
    """

    # Setup output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = url.replace("https://", "").replace("http://", "").split("/")[0]

    telemetry = {
        "url": url,
        "domain": domain,
        "captured_at": timestamp,
        "network_requests": [],
        "cookies": [],
        "console_logs": [],
        "security_headers": {},
        "dom_content": ""
    }

    print(f"\n[*] Starting telemetry collection for: {url}")
    print(f"[*] Output directory: {output_dir}/\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            record_har_path=str(output_path / f"{domain}_{timestamp}.har")
        )
        page = await context.new_page()

        # ── 1. CONSOLE LOGS ──────────────────────────────────────────────
        def handle_console(msg):
            telemetry["console_logs"].append({
                "type": msg.type,
                "text": msg.text,
                "location": msg.location
            })

        page.on("console", handle_console)

        # ── 2. NETWORK REQUESTS ──────────────────────────────────────────
        def handle_request(request):
            telemetry["network_requests"].append({
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
                "headers": dict(request.headers),
                "post_data": request.post_data
            })

        def handle_response(response):
            # Capture security headers from main document responses
            if response.request.resource_type == "document":
                headers = dict(response.headers)
                security_keys = [
                    "content-security-policy",
                    "strict-transport-security",
                    "x-frame-options",
                    "x-content-type-options",
                    "referrer-policy",
                    "permissions-policy",
                    "x-xss-protection"
                ]
                telemetry["security_headers"] = {
                    k: headers[k] for k in security_keys if k in headers
                }

        page.on("request", handle_request)
        page.on("response", handle_response)

        # ── 3. NAVIGATE & WAIT FOR FULL LOAD ────────────────────────────
        print(f"[*] Navigating to {url} ...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)  # Extra wait for late-firing trackers

        # ── 4. COOKIES ──────────────────────────────────────────────────
        print("[*] Capturing cookies ...")
        raw_cookies = await context.cookies()
        for cookie in raw_cookies:
            telemetry["cookies"].append({
                "name": cookie["name"],
                "domain": cookie["domain"],
                "path": cookie["path"],
                "secure": cookie["secure"],
                "httpOnly": cookie["httpOnly"],
                "sameSite": cookie.get("sameSite", "None"),
                "expires": cookie.get("expires", -1)
            })

        # ── 5. DOM CONTENT ───────────────────────────────────────────────
        print("[*] Capturing DOM content ...")
        telemetry["dom_content"] = await page.content()

        # ── 6. CLOSE & SAVE HAR ─────────────────────────────────────────
        await context.close()
        await browser.close()

    # ── 7. SAVE ALL TELEMETRY TO JSON ────────────────────────────────────
    output_file = output_path / f"{domain}_{timestamp}_telemetry.json"

    # Don't store full DOM in JSON (save separately)
    dom_file = output_path / f"{domain}_{timestamp}_dom.html"
    dom_file.write_text(telemetry["dom_content"], encoding="utf-8")
    telemetry_json = {k: v for k, v in telemetry.items() if k != "dom_content"}
    telemetry_json["dom_file"] = str(dom_file)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(telemetry_json, f, indent=2, default=str)

    # ── 8. PRINT SUMMARY ─────────────────────────────────────────────────
    print("\n" + "="*55)
    print("           TELEMETRY COLLECTION SUMMARY")
    print("="*55)
    print(f"  Target URL       : {url}")
    print(f"  Network Requests : {len(telemetry['network_requests'])}")
    print(f"  Cookies          : {len(telemetry['cookies'])}")
    print(f"  Console Logs     : {len(telemetry['console_logs'])}")
    print(f"  Security Headers : {len(telemetry['security_headers'])}")
    print(f"  HAR File         : {domain}_{timestamp}.har")
    print(f"  JSON Output      : {output_file.name}")
    print(f"  DOM File         : {dom_file.name}")
    print("="*55)

    if telemetry["security_headers"]:
        print("\n  Security Headers Found:")
        for k, v in telemetry["security_headers"].items():
            print(f"    - {k}: {v[:60]}...")
    else:
        print("\n  ⚠ No security headers detected — potential compliance risk!")

    if telemetry["cookies"]:
        print(f"\n  Sample Cookies ({min(3, len(telemetry['cookies']))} of {len(telemetry['cookies'])}):")
        for c in telemetry["cookies"][:3]:
            print(f"    - {c['name']} | secure={c['secure']} | httpOnly={c['httpOnly']} | sameSite={c['sameSite']}")

    print("\n[✓] Telemetry collection complete.\n")
    return telemetry_json


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Default test URL — change this to any target site
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://bbc.com"

    asyncio.run(collect_telemetry(target_url))
