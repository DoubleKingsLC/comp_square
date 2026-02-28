"""
Policy Document Scraper — Phase 1 of LLM-Driven Privacy Compliance Framework
Pulls: Privacy Policy, Terms & Conditions, Cookie Policy, Data Retention Policy,
       and any other policy documents found on the site.

Discovery Strategy:
  1. Read policy_links from telemetry JSON (if available)
  2. Crawl the site's homepage/footer as fallback
  3. Save each document as clean Markdown for RAG pipeline

Author: Aaron Joseph Jean — 25233118
"""

from __future__ import annotations

import json
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ─────────────────────────────────────────────────────────────────────────────
# POLICY KEYWORD CATEGORIES
# Ordered by priority — first match wins for document type labelling
# ─────────────────────────────────────────────────────────────────────────────
POLICY_CATEGORIES = {
    "privacy_policy": [
        "privacy policy", "privacy notice", "privacy statement",
        "data privacy", "privacy"
    ],
    "cookie_policy": [
        "cookie policy", "cookie notice", "cookie statement",
        "cookies"
    ],
    "terms_and_conditions": [
        "terms and conditions", "terms of service", "terms of use",
        "user agreement", "terms & conditions", "terms"
    ],
    "data_retention_policy": [
        "data retention", "retention policy", "data storage",
        "data lifecycle"
    ],
    "other_policy": [
        "policy", "legal", "gdpr", "data protection", "acceptable use",
        "community guidelines", "disclaimer", "compliance"
    ]
}

# All keywords flattened for quick link matching
ALL_POLICY_KEYWORDS = [kw for kws in POLICY_CATEGORIES.values() for kw in kws]


# URLs containing these fragments are very likely direct policy docs (high confidence)
DIRECT_URL_SIGNALS = {
    "privacy_policy":        ["/privacy-policy", "/privacy_policy", "/privacy/policy", "privacypolicy"],
    "cookie_policy":         ["/cookie-policy", "/cookie_policy", "/cookies"],
    "terms_and_conditions":  ["/terms-of-service", "/terms-and-conditions", "/terms_of_service",
                              "/tos", "/user-agreement", "/terms/"],
    "data_retention_policy": ["/data-retention", "/retention-policy"],
}

# URLs with these fragments are navigation/hub pages — deprioritise them
WEAK_URL_SIGNALS = ["search", "center", "hub", "topics", "manage", "settings", "about"]


def score_url(url: str) -> int:
    """Return a quality score for a policy URL — higher = more likely a full doc."""
    u = url.lower()
    score = 0
    for signals in DIRECT_URL_SIGNALS.values():
        if any(s in u for s in signals):
            score += 10
    if any(w in u for w in WEAK_URL_SIGNALS):
        score -= 5
    # Shorter paths = less navigation nesting = more likely a direct doc
    score -= url.count("/")
    return score


def classify_policy(url: str, text: str) -> str:
    """Classify a policy link into one of the known categories."""
    combined = (url + " " + text).lower()
    # Check direct URL signals first (high confidence)
    for category, signals in DIRECT_URL_SIGNALS.items():
        if any(s in combined for s in signals):
            return category
    # Fall back to keyword matching
    for category, keywords in POLICY_CATEGORIES.items():
        if any(kw in combined for kw in keywords):
            return category
    return "other_policy"


def is_policy_link(href: str, text: str) -> bool:
    """Return True if a link looks like a policy document."""
    combined = (href + " " + text).lower()
    return any(kw in combined for kw in ALL_POLICY_KEYWORDS)


def html_to_markdown(soup: BeautifulSoup, base_url: str = "") -> str:
    """
    Convert BeautifulSoup HTML to clean Markdown.
    Uses iterative tag-by-tag approach — no recursion, no NavigableString issues.
    """
    # Strip all noise first
    for tag in soup(["script", "style", "svg", "noscript", "iframe",
                     "nav", "header", "footer", "aside", "form",
                     "button", "input", "select", "textarea"]):
        tag.decompose()

    body  = soup.find("main") or soup.find("article") or soup.find("body") or soup
    lines = []

    # Walk every tag in document order
    for el in body.find_all(True):
        try:
            tag = el.name
            if not tag:
                continue

            if tag in ("h1","h2","h3","h4","h5","h6"):
                text = el.get_text(separator=" ", strip=True)
                if text:
                    level = int(tag[1])
                    lines.append(f"\n{'#' * level} {text}\n")

            elif tag == "p":
                text = el.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"\n{text}\n")

            elif tag == "li":
                text = el.get_text(separator=" ", strip=True)
                parent = el.parent.name if el.parent else "ul"
                if text:
                    lines.append(f"- {text}")

            elif tag == "table":
                for r_idx, row in enumerate(el.find_all("tr")):
                    cells = row.find_all(["th","td"])
                    if cells:
                        row_text = " | ".join(c.get_text(strip=True) for c in cells)
                        lines.append(f"| {row_text} |")
                        if r_idx == 0:
                            lines.append("|" + " --- |" * len(cells))
                lines.append("")

            elif tag == "a":
                # Only top-level links (not inside p/li — those get captured by parent)
                if el.parent and el.parent.name not in ("p","li","td","th","span","div"):
                    text = el.get_text(strip=True)
                    href = el.get("href","")
                    if href and base_url:
                        href = urljoin(base_url, href)
                    if text:
                        lines.append(f"[{text}]({href})" if href else text)

            elif tag == "hr":
                lines.append("\n---\n")

        except Exception:
            continue

    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


async def discover_policy_links_from_crawl(page, base_url: str) -> list:
    """
    Crawl homepage and common footer/sitemap pages to find policy links.
    Used as fallback when telemetry JSON has no policy_links.
    """
    found = []
    visited = set()

    async def scan_page(url):
        if url in visited:
            return
        visited.add(url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            links = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: (a.innerText || a.textContent || '').trim().substring(0, 120)
                }))
            """)
            for link in links:
                href = link.get("href", "")
                text = link.get("text", "")
                if href and is_policy_link(href, text):
                    found.append({"href": href, "text": text})
        except Exception as e:
            print(f"  [!] Crawl error on {url}: {e}")

    parsed   = urlparse(base_url)
    homepage = f"{parsed.scheme}://{parsed.netloc}"

    # Pages most likely to contain policy links
    crawl_targets = [
        homepage,
        f"{homepage}/sitemap",
        f"{homepage}/legal",
        f"{homepage}/about",
    ]

    print(f"  [*] Crawling {len(crawl_targets)} pages for policy links ...")
    for target in crawl_targets:
        await scan_page(target)

    # Deduplicate by href
    seen  = set()
    deduped = []
    for link in found:
        if link["href"] not in seen:
            seen.add(link["href"])
            deduped.append(link)

    return deduped


async def scrape_policy(page, url: str, category: str, domain: str,
                         output_path: Path) -> dict | None:
    """
    Navigate to a policy URL, extract clean text, save as Markdown.
    Handles JS-rendered / SPA pages by scrolling and waiting for content.
    Returns a metadata dict or None on failure.
    """
    print(f"\n  [→] Fetching [{category}]: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Scroll page to trigger lazy-loaded content (common on SPA policy pages)
        await page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let total = 0;
                    const step = 600;
                    const timer = setInterval(() => {
                        window.scrollBy(0, step);
                        total += step;
                        if (total >= document.body.scrollHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 120);
                    setTimeout(() => { clearInterval(timer); resolve(); }, 8000);
                });
            }
        """)
        await asyncio.sleep(2)
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # Try extracting via innerText first (best for JS-rendered SPAs)
        raw_text = await page.evaluate("""
            () => {
                // Remove noise elements
                ['script','style','nav','header','footer','aside'].forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => el.remove());
                });
                const main = document.querySelector('main')
                    || document.querySelector('article')
                    || document.querySelector('[role="main"]')
                    || document.querySelector('.policy-content')
                    || document.querySelector('.privacy-content')
                    || document.querySelector('.legal-content')
                    || document.body;
                return main ? main.innerText : document.body.innerText;
            }
        """)

        # Also get HTML for structured markdown conversion
        raw_html = await page.content()
        soup     = BeautifulSoup(raw_html, "html.parser")
        title    = soup.title.get_text(strip=True) if soup.title else category.replace("_", " ").title()

        # Convert HTML to structured markdown
        markdown_content = html_to_markdown(soup, base_url=url)

        # If markdown is too short (JS-heavy SPA), fall back to plain innerText
        if len(markdown_content.strip()) < 300 and raw_text and len(raw_text.strip()) > 300:
            print(f"  [~] HTML parse thin — using innerText fallback")
            # Convert plain text to basic markdown
            lines = []
            for line in raw_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Heuristic: short ALL-CAPS or title-case lines = headings
                if len(line) < 80 and (line.isupper() or (line.istitle() and len(line.split()) < 10)):
                    lines.append(f"\n## {line}\n")
                else:
                    lines.append(line)
            markdown_content = "\n".join(lines)

        if len(markdown_content.strip()) < 100:
            print(f"  [!] Content still too short after all attempts — skipping {url}")
            return None

        ts        = datetime.now(timezone.utc).isoformat()
        safe_name = re.sub(r"[^\w\-]", "_", category)
        filename  = f"{domain}_{safe_name}.md"
        filepath  = output_path / filename

        document = f"""---
title: {title}
category: {category}
source_url: {url}
domain: {domain}
scraped_at: {ts}
---

# {title}

> **Source:** {url}
> **Scraped:** {ts}

---

{markdown_content}
"""

        filepath.write_text(document, encoding="utf-8")
        word_count = len(markdown_content.split())
        print(f"  [✓] Saved → {filename}  ({word_count:,} words)")

        return {
            "category":   category,
            "url":        url,
            "filename":   filename,
            "word_count": word_count,
            "scraped_at": ts
        }

    except Exception as e:
        print(f"  [✗] Failed to scrape {url}: {e}")
        return None


async def collect_policies(
    target_url: str,
    telemetry_json: str | None = None,
    output_dir: str = "policy_documents"
) -> dict:
    """
    Main entry point. Discovers and scrapes all policy documents for a site.

    Args:
        target_url     : The website homepage URL
        telemetry_json : Path to telemetry JSON from telemetry_collector.py (optional)
        output_dir     : Folder to save Markdown policy documents

    Returns:
        dict: Summary of all scraped policies
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parsed  = urlparse(target_url)
    domain  = parsed.netloc
    ts_safe = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*62}")
    print(f"  POLICY SCRAPER — LLM Privacy Compliance Framework")
    print(f"{'='*62}")
    print(f"  Target  : {target_url}")
    print(f"  Domain  : {domain}")
    print(f"  Output  : {output_dir}/")
    print(f"{'='*62}\n")

    # ── Step 1: Load policy links from telemetry JSON ─────────────────────────
    telemetry_links = []
    if telemetry_json:
        try:
            with open(telemetry_json, "r") as f:
                telemetry_data = json.load(f)
            telemetry_links = (
                telemetry_data
                .get("declared_vs_observed", {})
                .get("policy_links", [])
            )
            print(f"[*] Loaded {len(telemetry_links)} policy link(s) from telemetry JSON.")
        except Exception as e:
            print(f"[!] Could not load telemetry JSON: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # ── Step 2: Crawl as fallback if no telemetry links ───────────────────
        if not telemetry_links:
            print("[*] No telemetry links — crawling site for policy links ...")
            telemetry_links = await discover_policy_links_from_crawl(page, target_url)
            print(f"[*] Found {len(telemetry_links)} policy link(s) via crawl.")
        else:
            # Still crawl homepage to catch any links telemetry may have missed
            print("[*] Augmenting telemetry links with homepage crawl ...")
            crawl_links = await discover_policy_links_from_crawl(page, target_url)
            existing_hrefs = {l["href"] for l in telemetry_links}
            for link in crawl_links:
                if link["href"] not in existing_hrefs:
                    telemetry_links.append(link)
                    existing_hrefs.add(link["href"])
            print(f"[*] Total unique policy links: {len(telemetry_links)}")

        if not telemetry_links:
            print("[!] No policy links found. Exiting.")
            await browser.close()
            return {}

        # ── Step 3: Classify and pick BEST URL per category via scoring ─────────
        print(f"\n[*] Classifying {len(telemetry_links)} links ...")

        # Well-known direct policy URL patterns as fallback candidates
        WELLKNOWN_PATHS = {
            "privacy_policy":        ["/privacy/policy", "/privacy-policy", "/legal/privacy-policy",
                                      "/en/privacy", "/policies/privacy"],
            "cookie_policy":         ["/cookies", "/legal/cookie-policy", "/cookie-policy",
                                      "/policies/cookies"],
            "terms_and_conditions":  ["/legal/terms", "/terms", "/tos",
                                      "/legal/user-agreement", "/policies/terms"],
            "data_retention_policy": ["/data-retention", "/legal/data-retention"],
        }

        base_origin = f"{parsed.scheme}://{parsed.netloc}"

        # Collect all scored candidates per category
        candidates = {}
        for link in telemetry_links:
            href = link.get("href", "")
            text = link.get("text", "")
            if href.startswith("/"):
                href = f"{base_origin}{href}"
            if not href.startswith("http"):
                continue
            link_domain = urlparse(href).netloc
            if domain not in link_domain and link_domain not in domain:
                continue
            category  = classify_policy(href, text)
            url_score = score_url(href)
            if category not in candidates:
                candidates[category] = []
            candidates[category].append({"href": href, "text": text, "score": url_score})

        # Add well-known fallback URLs as low-priority candidates
        for category, paths in WELLKNOWN_PATHS.items():
            for path in paths:
                fallback_url = f"{base_origin}{path}"
                if category not in candidates:
                    candidates[category] = []
                candidates[category].append({
                    "href": fallback_url, "text": "", "score": score_url(fallback_url) - 1
                })

        # Pick highest-scored URL per category
        categorised = {}
        for category, options in candidates.items():
            best = sorted(options, key=lambda x: x["score"], reverse=True)[0]
            categorised[category] = best
            print(f"  [+] {category:<30} -> {best['href']}  (score: {best['score']})")

        print(f"\n[*] Scraping {len(categorised)} unique policy document(s) ...\n")

        # ── Step 4: Scrape each policy page ───────────────────────────────────
        results = []
        for category, link in categorised.items():
            result = await scrape_policy(
                page, link["href"], category, domain, output_path
            )
            if result:
                results.append(result)

        await context.close()
        await browser.close()

    # ── Step 5: Save index JSON ───────────────────────────────────────────────
    index = {
        "target_url":       target_url,
        "domain":           domain,
        "scraped_at":       datetime.now(timezone.utc).isoformat(),
        "total_documents":  len(results),
        "documents":        results,
        "output_directory": str(output_path.resolve())
    }

    index_file = output_path / f"{domain}_{ts_safe}_policy_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  POLICY SCRAPER SUMMARY")
    print(f"{'='*62}")
    print(f"  Documents Scraped  : {len(results)}")
    for r in results:
        print(f"    ✓  {r['category']:<30} ({r['word_count']:,} words)")
    print(f"\n  Index File : {index_file.name}")
    print(f"  Output Dir : {output_path.resolve()}")
    print(f"\n[✓] Policy collection complete — ready for RAG pipeline.\n")

    return index


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 policy_scraper.py <url> [telemetry_json]")
        print("  url            : Target website (e.g. https://bmsit.ac.in)")
        print("  telemetry_json : Optional path to telemetry JSON from telemetry_collector.py")
        sys.exit(1)

    target  = sys.argv[1]
    t_json  = sys.argv[2] if len(sys.argv) > 2 else None

    asyncio.run(collect_policies(target, telemetry_json=t_json))