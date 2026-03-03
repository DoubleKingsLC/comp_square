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
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from typing import Dict, List, Any

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

try:
    from .llm_policy_assistant import (
        PolicyCandidate,
        select_policy_urls_via_llm,
        validate_policies_via_llm,
    )
except ImportError:
    from llm_policy_assistant import (
        PolicyCandidate,
        select_policy_urls_via_llm,
        validate_policies_via_llm,
    )


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


# Known corporate ecosystems where legal / policy documents are often hosted
# across multiple related domains.
TRUSTED_ECOSYSTEMS: Dict[str, set[str]] = {
    # Meta / Facebook ecosystem
    "facebook.com": {
        "facebook.com",
        "www.facebook.com",
        "about.fb.com",
        "instagram.com",
        "help.instagram.com",
        "meta.com",
        "whatsapp.com",
        "www.whatsapp.com",
    },
    "instagram.com": {
        "facebook.com",
        "www.facebook.com",
        "about.fb.com",
        "instagram.com",
        "help.instagram.com",
        "meta.com",
        "whatsapp.com",
        "www.whatsapp.com",
    },
    "meta.com": {
        "facebook.com",
        "www.facebook.com",
        "about.fb.com",
        "instagram.com",
        "help.instagram.com",
        "meta.com",
        "whatsapp.com",
        "www.whatsapp.com",
    },
    "whatsapp.com": {
        "facebook.com",
        "www.facebook.com",
        "about.fb.com",
        "instagram.com",
        "help.instagram.com",
        "meta.com",
        "whatsapp.com",
        "www.whatsapp.com",
    },

    # Alphabet / Google
    "google.com": {"google.com", "www.google.com", "alphabet.com", "youtube.com", "policies.google.com"},
    "youtube.com": {"google.com", "www.google.com", "alphabet.com", "youtube.com", "policies.google.com"},

    # Microsoft
    "microsoft.com": {"microsoft.com", "www.microsoft.com", "aka.ms", "office.com", "windows.com"},
    "office.com": {"microsoft.com", "www.microsoft.com", "aka.ms", "office.com", "windows.com"},
}

USER_AGENTS = [
    # A small pool of realistic, non-headless desktop Chrome UAs
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def get_root_domain(hostname: str) -> str:
    """Very lightweight eTLD+1-style extractor (good enough for big sites)."""
    hostname = hostname.lower().strip()
    if not hostname:
        return ""
    # Strip leading "www."
    if hostname.startswith("www."):
        hostname = hostname[4:]
    parts = hostname.split(".")
    if len(parts) <= 2:
        return hostname
    return ".".join(parts[-2:])


def is_trusted_domain(primary_domain: str, candidate_domain: str) -> bool:
    """
    Return True if candidate_domain is the same as, a subdomain of, or part of a
    trusted corporate ecosystem for primary_domain.
    """
    if not candidate_domain:
        return False

    primary_domain = primary_domain.lower()
    candidate_domain = candidate_domain.lower()

    # Direct match or subdomain relationship
    if primary_domain in candidate_domain or candidate_domain in primary_domain:
        return True

    primary_root = get_root_domain(primary_domain)
    candidate_root = get_root_domain(candidate_domain)
    ecosystem = TRUSTED_ECOSYSTEMS.get(primary_root)
    if ecosystem and (candidate_root in ecosystem or candidate_domain in ecosystem):
        return True

    return False


def score_url(url: str) -> int:
    """Return a quality score for a policy URL — higher = more likely a full doc."""
    u = url.lower()
    score = 0

    # High-confidence direct signals
    for signals in DIRECT_URL_SIGNALS.values():
        if any(s in u for s in signals):
            score += 10

    # Weak / navigation-like signals
    if any(w in u for w in WEAK_URL_SIGNALS):
        score -= 5

    # Language-aware signals: /en/ or /en-us/ etc near policy keywords
    path = urlparse(u).path
    if re.search(r"/(en|en-us|en-gb)(/|$)", path):
        if any(kw in path for kw in ("privacy", "policy", "cookies", "terms")):
            score += 15

    # Canonical endpoints like /privacy or /terms
    trimmed = path.rstrip("/") or "/"
    if trimmed.endswith("/privacy") or trimmed.endswith("/terms"):
        score += 20

    # Keyword proximity: strong boost when "privacy" appears very close to
    # "full" or "policy" in the URL string, which often indicates a
    # "full privacy policy" style endpoint.
    if re.search(r"(privacy.{0,3}(full|policy))|((full|policy).{0,3}privacy)", u):
        score += 30

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
    # Strip the most obvious noise first.
    for tag in soup(["script", "style", "svg", "iframe", "noscript"]):
        tag.decompose()

    # Some sites wrap real policy text in semantic containers like <nav>
    # or <header>. Only drop these if they are clearly short chrome.
    for container in soup.find_all(["nav", "header", "footer", "aside"]):
        try:
            text_len = len(container.get_text(separator=" ", strip=True))
        except Exception:
            text_len = 0
        # If the container has very little text, it's likely navigation / chrome.
        if text_len < 1000:
            container.decompose()

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


def extract_effective_date(text: str | None) -> str | None:
    """
    Extract an 'effective date' style string from raw text if present.
    Looks for patterns like:
      - Last updated: 1 January 2024
      - Effective date – 2024-01-01
      - Version: 1 March 2023
    """
    if not text:
        return None

    # Focus on the beginning and end of the document, where effective
    # dates and version strings usually live.
    if len(text) > 4000:
        snippet = text[:2000] + " " + text[-2000:]
    else:
        snippet = text

    patterns = [
        # Natural language dates
        r"(last\s+updated|effective\s+date|effective\s+from|version)\s*[:\-–]\s*"
        r"(\d{1,2}\s+[A-Z][a-z]{2,9}\s+\d{4})",
        r"(last\s+updated|effective\s+date|effective\s+from|version)\s*[:\-–]\s*"
        r"([A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4})",
        r"(last\s+updated|effective\s+date|effective\s+from|version)\s*[:\-–]\s*"
        r"(\d{4}-\d{2}-\d{2})",
        # Version-style strings, e.g. v1.2 or Version 2024.1
        r"(version|v\.?)\s*[:\-–]?\s*(\d+\.\d+)",
        r"(version)\s*[:\-–]?\s*(\d{4}\.\d+)",
    ]

    for pat in patterns:
        m = re.search(pat, snippet, flags=re.IGNORECASE)
        if m:
            return m.group(2).strip()
    return None


async def dismiss_consent_banners(page) -> None:
    """
    Best-effort dismissal of common GDPR / cookie consent overlays.
    Run immediately after page.goto where possible.
    """
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Allow all')",
        "button:has-text('Allow All')",
        "button:has-text('Agree')",
        "button:has-text('Got it')",
        "button[id*='cookie']",
        "[role='button'][id*='cookie']",
        "[data-testid='cookie-policy-manage-dialog-accept-button']",
    ]

    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.count():
                # Only click if the element is actually visible to avoid
                # triggering hidden controls.
                if await locator.is_visible():
                    await locator.click()
                    # Give the overlay some time to disappear
                    await page.wait_for_timeout(1000)
        except Exception:
            continue


async def discover_policy_links_from_crawl(page, base_url: str, primary_domain: str) -> list:
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
            await dismiss_consent_banners(page)
            links = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: (a.innerText || a.textContent || '').trim().substring(0, 120)
                }))
            """)
            for link in links:
                href = link.get("href", "")
                text = link.get("text", "")
                if not href:
                    continue
                if not is_policy_link(href, text):
                    continue
                link_domain = urlparse(href).netloc
                if not is_trusted_domain(primary_domain, link_domain):
                    continue
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
                         output_path: Path,
                         _depth: int = 0) -> dict | None:
    """
    Navigate to a policy URL, extract clean text, save as Markdown.
    Handles JS-rendered / SPA pages by scrolling and waiting for content.
    Returns a metadata dict or None on failure.
    """
    print(f"\n  [→] Fetching [{category}]: {url}")
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await dismiss_consent_banners(page)

        # Skeleton loader + scrollability detection: if common shimmer /
        # placeholder classes are present or the body is still non-
        # scrollable (overflow hidden with no scroll height), wait a bit
        # longer for real text to load.
        for _ in range(3):
            has_skeleton, body_blocked = await page.evaluate("""
                () => {
                    const clsTokens = ['shimmer', 'skeleton', 'placeholder', 'loading-state'];
                    const els = Array.from(document.querySelectorAll('[class]'));
                    const hasSkeleton = els.some(el => {
                        const cls = el.className.toString().toLowerCase();
                        return clsTokens.some(t => cls.includes(t));
                    });
                    const body = document.body;
                    if (!body) return [hasSkeleton, false];
                    const style = window.getComputedStyle(body);
                    const overflowY = style.overflowY || style.overflow;
                    const blocked = (overflowY === 'hidden' || overflowY === 'clip')
                        && body.scrollHeight <= body.clientHeight + 10;
                    return [hasSkeleton, blocked];
                }
            """)
            if has_skeleton or body_blocked:
                await asyncio.sleep(2)
            else:
                break

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
        await asyncio.sleep(5)
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # Try to expand "See more" / accordion-style sections that often
        # hide important policy text behind buttons or toggles.
        try:
            await page.evaluate("""
                () => {
                    const EXPAND_TOKENS = [
                        'see more', 'see details', 'learn more',
                        'view more', 'show more', 'more information',
                        'read more', 'expand', 'details'
                    ];

                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        if (!rect.width || !rect.height) return false;
                        const style = window.getComputedStyle(el);
                        if (style.visibility === 'hidden' || style.display === 'none') return false;
                        return true;
                    };

                    const clickIfExpandable = (el) => {
                        const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
                        if (!txt) return;
                        if (!isVisible(el)) return;
                        if (EXPAND_TOKENS.some(t => txt.includes(t))) {
                            try { el.click(); } catch (e) {}
                        }
                    };

                    // Buttons and clickable elements
                    document.querySelectorAll('button, [role="button"], a').forEach(clickIfExpandable);

                    // Generic accordions / disclosure widgets
                    document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                        if (!isVisible(el)) return;
                        try { el.click(); } catch (e) {}
                    });
                }
            """)
            await asyncio.sleep(2)
        except Exception:
            # Expansion is a best-effort enhancement; continue even if it fails.
            pass

        # Try extracting via innerText first (best for JS-rendered SPAs)
        raw_text = await page.evaluate("""
            () => {
                // Remove noise elements
                ['script','style'].forEach(tag => {
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

        word_count = len(markdown_content.split())

        # Semantic fallback: if the primary conversion produced less than
        # 500 words, re-scan the raw HTML but aggressively drop known junk
        # containers (chrome headers, global nav, etc.) and keep the
        # largest remaining policy-like region.
        if word_count < 500 and raw_html:
            soup_fallback = BeautifulSoup(raw_html, "html.parser")
            junk_id_tokens = [
                "globalnav", "siteheader", "site-footer", "cookie", "banner",
                "consent", "toolbar", "sidebar", "nav", "footer-header",
            ]
            for token in junk_id_tokens:
                # Remove elements whose id/class contains these tokens
                for el in soup_fallback.select(f"[id*='{token}'], [class*='{token}']"):
                    el.decompose()

            markdown_fallback = html_to_markdown(soup_fallback, base_url=url)
            if len(markdown_fallback.split()) > word_count:
                print("  [~] Using semantic fallback region for markdown")
                markdown_content = markdown_fallback
                word_count = len(markdown_content.split())

        # Detect "hub" pages that mostly route to sub-policies rather than
        # containing the full legal text themselves.
        if word_count < 500 and _depth < 2:
            policy_links = []
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                if not text:
                    continue
                lower = text.lower()
                if "policy" in lower or "privacy" in lower or "cookies" in lower or "terms" in lower:
                    href = urljoin(url, a["href"])
                    policy_links.append({"href": href, "text": text})

            if len(policy_links) > 5:
                # Treat this as a hub and perform a deeper search across the
                # best candidate links to find the most "legal-dense" page.
                print(f"  [~] Detected hub page for {category} — performing deep search")

                # Score sub-links and pick the top 3.
                scored = []
                for link in policy_links:
                    href = link["href"]
                    link_domain = urlparse(href).netloc
                    # Stay within the trusted ecosystem
                    if not is_trusted_domain(domain, link_domain):
                        continue
                    scored.append((score_url(href), href))

                if scored:
                    scored.sort(key=lambda x: x[0], reverse=True)
                    top_candidates = [u for _, u in scored[:3]]

                    async def _measure_legal_density(target_url: str) -> tuple[float, str]:
                        """Return (density, url) for ranking only; no file writes."""
                        try:
                            await page.goto(target_url, wait_until="networkidle", timeout=30000)
                            await dismiss_consent_banners(page)
                            text = await page.evaluate("""
                                () => {
                                    const main = document.querySelector('main')
                                        || document.querySelector('article')
                                        || document.querySelector('[role="main"]')
                                        || document.body;
                                    return main ? main.innerText : document.body.innerText;
                                }
                            """)
                            html = await page.content()
                            soup_local = BeautifulSoup(html, "html.parser")
                            links_local = soup_local.find_all("a", href=True)
                            num_links = max(1, len(links_local))
                            # Long sentences as a proxy for legal clauses
                            long_sentences = 0
                            if text:
                                for sent in re.split(r"[\.!?]", text):
                                    if len(sent.strip()) > 120:
                                        long_sentences += 1
                            density = long_sentences / num_links
                            return density, target_url
                        except Exception:
                            return 0.0, target_url

                    best_density = -1.0
                    best_url = None
                    for candidate in top_candidates:
                        density, u_candidate = await _measure_legal_density(candidate)
                        if density > best_density:
                            best_density = density
                            best_url = u_candidate

                    if best_url and best_url != url:
                        print(f"  [~] Deep search redirect → {best_url} (density={best_density:.3f})")
                        return await scrape_policy(page, best_url, category, domain, output_path, _depth + 1)

        # Thin document trigger: for very short pages, try a category-
        # specific deep link traversal before giving up.
        THIN_THRESHOLD = 300
        if word_count < THIN_THRESHOLD and _depth < 3:
            print(f"  [~] Thin document detected for {category} ({word_count} words) — re-evaluating sublinks")
            category_tokens = {
                "privacy_policy": ["privacy"],
                "cookie_policy": ["cookie", "cookies"],
                "terms_and_conditions": ["terms", "conditions"],
                "data_retention_policy": ["retention", "data retention"],
            }.get(category, [])

            deep_links = []
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = urljoin(url, a["href"])
                lowered = (href + " " + text).lower()
                if not any(tok in lowered for tok in category_tokens):
                    continue
                link_domain = urlparse(href).netloc
                if not is_trusted_domain(domain, link_domain):
                    continue
                deep_links.append({"href": href, "text": text})

            if deep_links:
                scored_deep = []
                for link in deep_links:
                    href = link["href"]
                    text = (link.get("text") or "").lower()
                    base_score = score_url(href)
                    # Contextual bonus for "full", "detail", etc.
                    bonus = 0
                    if any(w in text or w in href.lower() for w in ["full", "detail", "extended", "comprehensive"]):
                        bonus += 50
                    if "learn more" in text and any(tok in text for tok in category_tokens):
                        bonus += 50
                    scored_deep.append((base_score + bonus, href))

                scored_deep.sort(key=lambda x: x[0], reverse=True)
                best_href = scored_deep[0][1]
                if best_href != url:
                    print(f"  [~] Thin-doc redirect → {best_href}")
                    return await scrape_policy(page, best_href, category, domain, output_path, _depth + 1)

        if len(markdown_content.strip()) < 100:
            print(f"  [!] Content still too short after all attempts — skipping {url}")
            return None

        ts        = datetime.now(timezone.utc).isoformat()
        effective = extract_effective_date(raw_text or markdown_content)
        safe_name = re.sub(r"[^\w\-]", "_", category)
        filename  = f"{domain}_{safe_name}.md"
        filepath  = output_path / filename

        front_matter_lines = [
            "---",
            f"title: {title}",
            f"category: {category}",
            f"source_url: {url}",
            f"domain: {domain}",
            f"scraped_at: {ts}",
        ]
        if effective:
            front_matter_lines.append(f"effective_date: {effective}")
        front_matter_lines.append("---")

        document = (
            "\n".join(front_matter_lines)
            + f"""

# {title}

> **Source:** {url}
> **Scraped:** {ts}

---

{markdown_content}
"""
        )

        filepath.write_text(document, encoding="utf-8")
        print(f"  [✓] Saved → {filename}  ({word_count:,} words)")

        return {
            "category":   category,
            "url":        url,
            "filename":   filename,
            "word_count": word_count,
            "scraped_at": ts,
            "effective_date": effective,
        }

    except Exception as e:
        print(f"  [✗] Failed to scrape {url}: {e}")
        return None


async def collect_policies(
    target_url: str,
    telemetry_json: str | None = None,
    output_dir: str = "policy_documents",
    use_llm: bool = True,
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
    telemetry_links: list[dict] = []
    telemetry_data: dict[str, Any] = {}
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
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
            user_agent=random.choice(USER_AGENTS),
        )
        # Basic stealth: hide webdriver flag and spoof languages/plugins
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }]
            });
        """)
        page = await context.new_page()

        # ── Step 2: Crawl as fallback if no telemetry links ───────────────────
        if not telemetry_links:
            print("[*] No telemetry links — crawling site for policy links ...")
            telemetry_links = await discover_policy_links_from_crawl(page, target_url, domain)
            print(f"[*] Found {len(telemetry_links)} policy link(s) via crawl.")
        else:
            # Still crawl homepage to catch any links telemetry may have missed
            print("[*] Augmenting telemetry links with homepage crawl ...")
            crawl_links = await discover_policy_links_from_crawl(page, target_url, domain)
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
        candidates: dict[str, list[dict]] = {}
        for link in telemetry_links:
            href = link.get("href", "")
            text = link.get("text", "")
            if href.startswith("/"):
                href = f"{base_origin}{href}"
            if not href.startswith("http"):
                continue
            link_domain = urlparse(href).netloc
            if not is_trusted_domain(domain, link_domain):
                continue
            category  = classify_policy(href, text)
            url_score = score_url(href)
            # Avoid obvious "about us" / meta-products marketing pages
            combined_lt = (href + " " + text).lower()
            if (
                category == "other_policy"
                and url_score == 0
                and (("meta products" in combined_lt) or ("about us" in combined_lt))
            ):
                continue
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
                    "href": fallback_url,
                    "text": "",
                    "score": score_url(fallback_url) - 1,
                    "source": "wellknown",
                })

        # Ensure every candidate has a 'source' field
        for category, options in candidates.items():
            for opt in options:
                opt.setdefault("source", "telemetry_or_crawl")

        # ── LLM-assisted selection for privacy & cookie policies ──────────────
        categorised: dict[str, dict] = {}

        # Prepare candidates for LLM (only privacy + cookie)
        if use_llm and telemetry_data:
            llm_candidates: List[PolicyCandidate] = []
            for category in ("privacy_policy", "cookie_policy"):
                for opt in candidates.get(category, []):
                    llm_candidates.append(
                        PolicyCandidate(
                            category=category,
                            url=opt["href"],
                            text=opt.get("text", ""),
                            source=opt.get("source", "telemetry_or_crawl"),
                            score=opt.get("score", 0),
                        )
                    )

            # HAR path (if present) from telemetry meta
            har_path = None
            try:
                visual_ev = telemetry_data.get("visual_evidence", {})
                # telemetry_collector stores har in output listing, not in JSON,
                # but in case future versions add it, we pass it through.
                har_path = visual_ev.get("har_path")
            except Exception:
                har_path = None

            llm_selection = select_policy_urls_via_llm(
                domain=domain,
                telemetry_summary=telemetry_data,
                har_path=har_path,
                candidates=llm_candidates,
            )

            for cat_key, choice in llm_selection.items():
                chosen_url = choice.get("url")
                if not chosen_url:
                    continue
                # Find the matching candidate to retain text/score/source
                matched = None
                for opt in candidates.get(cat_key, []):
                    if opt["href"] == chosen_url:
                        matched = opt
                        break
                if matched is None:
                    matched = {
                        "href": chosen_url,
                        "text": "",
                        "score": score_url(chosen_url),
                        "source": "llm_only",
                    }
                categorised[cat_key] = matched
                print(
                    f"  [+] (LLM) {cat_key:<30} -> {matched['href']}  "
                    f"(score: {matched['score']})"
                )

        # Heuristic fallback for any categories not set by LLM (including
        # terms, data_retention, other_policy)
        for category, options in candidates.items():
            if category in categorised:
                continue
            best = sorted(options, key=lambda x: x["score"], reverse=True)[0]
            categorised[category] = best
            print(f"  [+] {category:<30} -> {best['href']}  (score: {best['score']})")

        print(f"\n[*] Scraping {len(categorised)} unique policy document(s) ...\n")

        # ── Step 4: Scrape each policy page ───────────────────────────────────
        results: list[dict] = []
        scraped_by_category: Dict[str, str] = {}
        for category, link in categorised.items():
            result = await scrape_policy(
                page, link["href"], category, domain, output_path
            )
            if result:
                results.append(result)
                try:
                    # Read back markdown we just wrote so that the LLM can
                    # validate that the correct documents were scraped.
                    md_path = output_path / result["filename"]
                    scraped_by_category[category] = md_path.read_text(encoding="utf-8")
                except Exception:
                    continue

        await context.close()
        await browser.close()

    # ── Step 5: Save index JSON ───────────────────────────────────────────────
    # Cross-category cookie extraction: if a standalone cookie policy is
    # missing or very thin, attempt to derive it from a cookies section
    # embedded inside the main privacy policy markdown.
    if "cookie_policy" not in scraped_by_category or len(scraped_by_category["cookie_policy"].split()) < 300:
        privacy_md = scraped_by_category.get("privacy_policy")
        if privacy_md:
            # Strip front matter if present
            parts = privacy_md.split("---", 2)
            body = parts[2] if len(parts) == 3 else privacy_md
            lines = body.splitlines()
            cookie_start = None
            cookie_end = None
            for i, line in enumerate(lines):
                if line.strip().lower().startswith("## cookies"):
                    cookie_start = i
                    break
            if cookie_start is not None:
                for j in range(cookie_start + 1, len(lines)):
                    if lines[j].startswith("## "):
                        cookie_end = j
                        break
                section_lines = lines[cookie_start:cookie_end] if cookie_end else lines[cookie_start:]
                cookie_section = "\n".join(section_lines).strip()
                if len(cookie_section.split()) > 150:
                    filename = f"{domain}_cookie_policy.md"
                    filepath = output_path / filename
                    ts = datetime.now(timezone.utc).isoformat()
                    front_matter = "\n".join(
                        [
                            "---",
                            f"title: Embedded Cookies Section - {domain}",
                            "category: cookie_policy",
                            f"source_url: {target_url}",
                            f"domain: {domain}",
                            f"scraped_at: {ts}",
                            "---",
                        ]
                    )
                    document = f"""{front_matter}

{cookie_section}
"""
                    filepath.write_text(document, encoding="utf-8")
                    scraped_by_category["cookie_policy"] = document
                    results.append(
                        {
                            "category": "cookie_policy",
                            "url": target_url,
                            "filename": filename,
                            "word_count": len(cookie_section.split()),
                            "scraped_at": ts,
                            "effective_date": None,
                        }
                    )
    # Optional LLM validation of scraped privacy / cookie policies
    llm_review: Dict[str, Any] = {}
    if use_llm and telemetry_data and scraped_by_category:
        selected_urls = {
            cat: info.get("href")
            for cat, info in categorised.items()
            if cat in ("privacy_policy", "cookie_policy") and info.get("href")
        }
        if selected_urls:
            try:
                llm_review = validate_policies_via_llm(
                    domain=domain,
                    telemetry_summary=telemetry_data,
                    selected_urls=selected_urls,
                    scraped_markdown_by_category=scraped_by_category,
                )
            except Exception:
                llm_review = {}

    index = {
        "target_url":       target_url,
        "domain":           domain,
        "scraped_at":       datetime.now(timezone.utc).isoformat(),
        "total_documents":  len(results),
        "documents":        results,
        "output_directory": str(output_path.resolve()),
        "llm_review":       llm_review,
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