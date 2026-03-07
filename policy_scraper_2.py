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
        "privacycenter.instagram.com",
        "privacycenter.facebook.com",
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
        "privacycenter.instagram.com",
        "privacycenter.facebook.com",
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
        "privacycenter.instagram.com",
        "privacycenter.facebook.com",
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

    # Weak / navigation-like signals — only check the URL path, not the hostname,
    # to avoid penalising dedicated policy subdomains like "privacycenter.instagram.com"
    _path_for_weak = urlparse(u).path.lower()
    if any(w in _path_for_weak for w in WEAK_URL_SIGNALS):
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


# URL fragments that indicate a settings/management page, not a policy document.
# These should be treated as navigable pages to FIND policies, not as policies themselves.
MANAGEMENT_URL_TOKENS = [
    "settings", "manage", "preferences", "opt-out", "opt_out",
    "cookie_settings", "cookie-settings", "consent_settings",
]


def classify_policy(url: str, text: str) -> str:
    """Classify a policy link into one of the known categories."""
    url_lower = url.lower()
    combined = (url_lower + " " + text.lower())
    # Settings/management pages are NOT policy documents — mark as other_policy so
    # they don't steal the privacy_policy or cookie_policy slot (e.g. Instagram's
    # /privacy/cookie_settings/ URL would otherwise match "privacy").
    if any(tok in url_lower for tok in MANAGEMENT_URL_TOKENS):
        return "other_policy"
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
    Uses NavigableString traversal to avoid duplicating text from nested containers.
    """
    import bs4
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
        if text_len < 1000:
            container.decompose()

    body = soup.find("main") or soup.find("article") or soup.find("body") or soup
    
    blocks = []
    current_block = []
    
    def flush_block():
        if current_block:
            blocks.append("".join(current_block).strip())
            current_block.clear()

    list_counters = {}

    for element in body.descendants:
        if isinstance(element, bs4.element.NavigableString):
            text = str(element).strip()
            if not text:
                continue
                
            parent = element.parent
            if parent.name in ["script", "style", "noscript"]:
                continue
                
            # Handle Headings
            if parent.name and re.match(r"^h[1-6]$", parent.name, re.I):
                level = int(parent.name[1])
                flush_block()
                blocks.append(f"\n{'#' * level} {text}\n")
                continue
                
            prefix = ""
            suffix = ""
            
            # Handle Lists
            li = parent.find_parent("li")
            if li and li not in list_counters:
                flush_block()
                list_counters[li] = True
                ol = li.find_parent("ol")
                if ol:
                    idx = len([sib for sib in li.previous_siblings if sib.name == "li"]) + 1
                    prefix = f"{idx}. "
                else:
                    prefix = "- "
                    
            # Handle inline formatting
            if parent.name in ["strong", "b"]:
                prefix += "**"
                suffix = "**"
            elif parent.name in ["em", "i"]:
                prefix += "*"
                suffix = "*"
            elif parent.name == "a":
                href = parent.get("href", "")
                if href and href.startswith("/"):
                    href = urljoin(base_url, href)
                suffix = f"]({href})"
                prefix += "["
                
            current_block.append(f"{prefix}{text}{suffix} ")
            
        elif isinstance(element, bs4.element.Tag):
            if element.name in ["p", "div", "section", "article", "br", "li"]:
                flush_block()
            elif element.name == "table":
                flush_block()
                for r_idx, row in enumerate(element.find_all("tr")):
                    cells = row.find_all(["th","td"])
                    if cells:
                        row_text = " | ".join(c.get_text(separator=" ", strip=True) for c in cells)
                        blocks.append(f"| {row_text} |")
                        if r_idx == 0:
                            blocks.append("|" + " --- |" * len(cells))
                blocks.append("")
                # Tell bs4 to drop this so we don't process strings again
                element.decompose()
                
    flush_block()

    md = "\n\n".join(b for b in blocks if b)
    
    # Clean up orphaned symbols and excessive newlines
    md = re.sub(r'(?m)^[\$\/\\\s]+$', '', md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = md.replace('/$', '').replace('$/', '').replace('$', '')
    
    # ── Advanced Block Deduplication ────────────────────────────────────
    # Sites like Instagram render expanded/collapsed accordion states
    # simultaneously in the DOM, causing massive block duplication.
    # We deduplicate at the block level (paragraphs/lists).
    raw_blocks = [b.strip() for b in md.split("\n\n") if b.strip()]
    unique_blocks = []
    
    for i, current_block in enumerate(raw_blocks):
        if not current_block:
            continue
            
        # For very short blocks (like headings "Privacy Policy"), keep them
        if len(current_block) < 30:
            unique_blocks.append(current_block)
            continue
            
        # Check against the last 3 added blocks to catch immediate repeats
        # resulting from duplicated React subtrees or adjacent mobile/desktop divs
        is_duplicate = False
        simplified_current = re.sub(r'[\W_]+', '', current_block.lower())
        
        for prev_block in unique_blocks[-3:]:
            simplified_prev = re.sub(r'[\W_]+', '', prev_block.lower())
            # If the text content is 95%+ identical (ignoring formatting), drop it
            if simplified_current == simplified_prev or simplified_current in simplified_prev:
                is_duplicate = True
                break
                
        if not is_duplicate:
            unique_blocks.append(current_block)
            
    return "\n\n".join(unique_blocks)

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


async def extract_links_from_consent_popup(page, base_url: str, primary_domain: str) -> list:
    """
    Extract policy links from visible cookie/consent banners and dialogs BEFORE
    dismissing them. Instagram and similar sites put cookie policy links only inside
    these popups, so we must harvest them first.
    Returns list of dicts with source='consent_popup'.
    """
    try:
        links = await page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                const addLink = (a, ctx) => {
                    const href = (a.href || '').trim();
                    const text = (a.innerText || a.textContent || '').trim();
                    if (!href || seen.has(href)) return;
                    seen.add(href);
                    results.push({ href, text, context: ctx });
                };
                // Ordered from most-specific to broadest — covers Instagram,
                // OneTrust, Cookiebot, and generic GDPR overlays
                const POPUP_SELS = [
                    '[data-testid*="cookie"]',
                    '[data-testid*="consent"]',
                    '[id*="onetrust"]',
                    '[id*="cookiebot"]',
                    '[id*="cookie-banner"]',
                    '[id*="cookie_banner"]',
                    '[id*="cookie-notice"]',
                    '[id*="cookie_notice"]',
                    '[id*="cookie-consent"]',
                    '[id*="cookie_consent"]',
                    '[id*="gdpr"]',
                    '[id*="consent"]',
                    '[class*="CookieBanner"]',
                    '[class*="cookieBanner"]',
                    '[class*="cookie-banner"]',
                    '[class*="cookie-notice"]',
                    '[class*="cookie-consent"]',
                    '[class*="consent-banner"]',
                    '[class*="consent-dialog"]',
                    '[class*="gdpr"]',
                    '[role="dialog"]',
                    '[role="alertdialog"]',
                ];
                for (const sel of POPUP_SELS) {
                    try {
                        document.querySelectorAll(sel).forEach(el => {
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden') return;
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0 && rect.height === 0) return;
                            el.querySelectorAll('a[href]').forEach(a => addLink(a, 'consent_popup'));
                        });
                    } catch(e) {}
                }
                // Fallback: scan fixed-position / high-z-index overlays that may not
                // use semantic class names (catches Instagram's obfuscated React components)
                try {
                    document.querySelectorAll('div, section, aside').forEach(el => {
                        try {
                            const style = window.getComputedStyle(el);
                            const zIdx = parseInt(style.zIndex) || 0;
                            if (style.position !== 'fixed' && zIdx < 100) return;
                            if (style.display === 'none' || style.visibility === 'hidden') return;
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) return;
                            el.querySelectorAll('a[href]').forEach(a => addLink(a, 'consent_popup'));
                        } catch(e) {}
                    });
                } catch(e) {}
                return results;
            }
        """)
    except Exception:
        return []

    result = []
    seen_hrefs: set = set()
    for link in links:
        href = urljoin(base_url, link.get("href", "").strip())
        text = link.get("text", "").strip()
        if not href.startswith("http") or href in seen_hrefs:
            continue
        if not is_policy_link(href, text):
            continue
        if not is_trusted_domain(primary_domain, urlparse(href).netloc):
            continue
        seen_hrefs.add(href)
        result.append({"href": href, "text": text, "source": "consent_popup", "context": "consent_popup"})
        print(f"  [consent_popup] {text[:30]:<30} -> {href[:60]}")
    return result


async def dismiss_consent_banners(page) -> None:
    """
    Best-effort dismissal of common GDPR / cookie consent overlays.
    Run immediately after page.goto where possible.
    Call extract_links_from_consent_popup() BEFORE this to harvest policy links.
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
        "[data-testid*='cookie'][data-testid*='accept']",
        "[data-testid*='consent'][data-testid*='accept']",
        "button:has-text('Allow all cookies')",
        "button:has-text('Accept all cookies')",
        "button:has-text('Accept all')",
        "#onetrust-accept-btn-handler",
        ".cc-accept",
        "[id*='accept'][id*='cookie']",
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


async def extract_priority_policy_links(page, base_url: str, primary_domain: str) -> list:
    """
    Priority pass: scan sign-in/login page first (discovered from homepage link text),
    then homepage. Returns dicts with source="priority_signin" or "priority_homepage".
    Prepended to candidate pool so they win the scoring race.
    """
    found = []
    seen  = set()
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    LOGIN_TOKENS = [
        "log in", "login", "sign in", "signin",
        "sign up", "signup", "register", "create account",
        "get started", "join", "create an account",
    ]

    # Well-known login/signup paths — tried as fallback when DOM discovery yields nothing.
    COMMON_AUTH_PATHS = [
        "/login", "/signin", "/sign-in", "/accounts/login",
        "/auth/login", "/auth/signin", "/user/login",
        "/signup", "/sign-up", "/register", "/accounts/signup",
        "/join", "/create-account",
    ]

    async def _collect_policy_links_from_page(url: str, source_label: str) -> bool:
        nonlocal found, seen
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if resp and resp.status >= 400:
                return False
            if any(s in page.url.lower() for s in ["404", "not-found", "error"]):
                return False
            # Wait for React/SPA to render consent popup before extracting
            await asyncio.sleep(1.5)
            # Harvest policy links from consent popup BEFORE dismissing it
            popup_links = await extract_links_from_consent_popup(page, url, primary_domain)
            for pl in popup_links:
                if pl["href"] not in seen:
                    seen.add(pl["href"])
                    found.insert(0, pl)  # consent_popup links get highest priority
            await dismiss_consent_banners(page)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(0.8)
            links = await page.evaluate("""
                () => {
                    const results = [];
                    const seen = new Set();
                    const addLink = (a, ctx) => {
                        const href = (a.href || '').trim();
                        const text = (a.innerText || a.textContent || '').trim();
                        if (!href || seen.has(href)) return;
                        seen.add(href);
                        results.push({ href, text, context: ctx });
                    };
                    const FORM_SELS = [
                        'form', '[class*="signup"]', '[class*="sign-up"]',
                        '[class*="register"]', '[class*="registration"]',
                        '[id*="signup"]', '[id*="sign-up"]',
                        '[id*="register"]', '[id*="registration"]',
                        '[data-testid*="signup"]', '[data-testid*="register"]',
                    ];
                    for (const sel of FORM_SELS) {
                        document.querySelectorAll(sel).forEach(el => {
                            let ancestor = el;
                            for (let i = 0; i < 4; i++) {
                                if (!ancestor.parentElement) break;
                                ancestor = ancestor.parentElement;
                            }
                            ancestor.querySelectorAll('a[href]').forEach(a => addLink(a, 'form'));
                        });
                    }
                    const AGREE_PATTERNS = [
                        'by registering', 'by signing up', 'by creating an account',
                        'by continuing', 'by clicking', 'i agree to', 'you agree to',
                        'terms of service', 'privacy notice', 'privacy policy',
                        'terms and conditions',
                    ];
                    document.querySelectorAll('p, span, div, label, small').forEach(el => {
                        const t = (el.innerText || el.textContent || '').toLowerCase();
                        if (AGREE_PATTERNS.some(p => t.includes(p))) {
                            el.querySelectorAll('a[href]').forEach(a => addLink(a, 'agreement'));
                        }
                    });
                    const FOOTER_SELS = [
                        'footer', '[role="contentinfo"]',
                        '[class*="footer"]', '[id*="footer"]',
                    ];
                    for (const sel of FOOTER_SELS) {
                        const footer = document.querySelector(sel);
                        if (footer) {
                            footer.querySelectorAll('a[href]').forEach(a => addLink(a, 'footer'));
                            break;
                        }
                    }
                    return results;
                }
            """)
            newly = 0
            for link in links:
                href = urljoin(url, link.get("href", "").strip())
                text = link.get("text", "").strip()
                ctx  = link.get("context", "")
                if not href.startswith("http") or href in seen:
                    continue
                if not is_policy_link(href, text):
                    continue
                if not is_trusted_domain(primary_domain, urlparse(href).netloc):
                    continue
                seen.add(href)
                found.append({"href": href, "text": text, "source": source_label, "context": ctx})
                print(f"  [priority/{source_label}/{ctx}] {text[:30]:<30} -> {href[:50]}")
                newly += 1
            return newly > 0
        except Exception:
            return False

    print("  [*] Priority scan: loading homepage to find sign-in/login links ...")
    try:
        await page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
        # Wait for React/SPA to render consent popup (popups load after JS executes)
        await asyncio.sleep(2.5)
        # Harvest consent popup links BEFORE dismissing the banner
        popup_links = await extract_links_from_consent_popup(page, base_url, primary_domain)
        for pl in popup_links:
            if pl["href"] not in seen:
                seen.add(pl["href"])
                found.insert(0, pl)
        await dismiss_consent_banners(page)
        await asyncio.sleep(0.5)
    except Exception:
        pass

    # ── Comprehensive login/signup element discovery ──────────────────────
    # Scans <a>, <button>, [role="button"], and onclick-bearing elements.
    # Extracts URLs from: href, data-href, formaction, onclick JS, and
    # the closest parent <a>.  Matches against visible text AND aria-label.
    all_interactive = await page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();

            // Extract a URL-like string from an onclick attribute value.
            const extractOnclickUrl = (onclick) => {
                if (!onclick) return '';
                // window.location = '/login'  or  location.href='/signup'
                const locMatch = onclick.match(
                    /(?:window\.)?location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/
                );
                if (locMatch) return locMatch[1];
                // window.open('/login', ...)
                const openMatch = onclick.match(
                    /window\.open\s*\(\s*['"]([^'"]+)['"]/
                );
                if (openMatch) return openMatch[1];
                // navigate('/login')  or  router.push('/login')
                const navMatch = onclick.match(
                    /(?:navigate|push|replace)\s*\(\s*['"]([^'"]+)['"]/
                );
                if (navMatch) return navMatch[1];
                return '';
            };

            // All clickable / interactive elements that could be a login CTA.
            const SELS = 'a[href], button, [role="button"], [onclick]';
            document.querySelectorAll(SELS).forEach(el => {
                // --- Resolve visible text + aria-label ---
                const visibleText = (el.innerText || el.textContent || '').trim();
                const ariaLabel   = (el.getAttribute('aria-label') || '').trim();
                const title       = (el.getAttribute('title') || '').trim();
                const text = (visibleText || ariaLabel || title).substring(0, 120);

                // --- Resolve destination URL from multiple sources ---
                let href = '';

                // 1. Standard href (works for <a> elements)
                if (el.href) {
                    href = el.href;
                }
                // 2. data-href / data-url custom attributes
                if (!href) {
                    href = el.getAttribute('data-href')
                        || el.getAttribute('data-url')
                        || el.getAttribute('data-link') || '';
                }
                // 3. formaction (on <button> inside a <form>)
                if (!href && el.formAction && el.formAction !== window.location.href) {
                    href = el.formAction;
                }
                // 4. Closest parent <a> (button wrapped inside a link)
                if (!href) {
                    const parentA = el.closest('a[href]');
                    if (parentA && parentA.href) href = parentA.href;
                }
                // 5. onclick attribute URL extraction
                if (!href) {
                    href = extractOnclickUrl(el.getAttribute('onclick'));
                }

                href = (href || '').trim();
                if (!href || href === '#' || href.startsWith('javascript:')) return;
                if (seen.has(href)) return;
                seen.add(href);

                results.push({ href, text });
            });

            // Also scan <form> action attributes — some login forms
            // use action="/accounts/login" without a visible link.
            document.querySelectorAll('form[action]').forEach(form => {
                const action = (form.action || '').trim();
                if (!action || action === '#' || seen.has(action)) return;
                seen.add(action);
                results.push({ href: action, text: 'form_action' });
            });

            return results;
        }
    """)

    signin_urls = []
    seen_signin = set()
    for lnk in all_interactive:
        href = (lnk.get("href") or "").strip()
        text = (lnk.get("text") or "").lower()
        if not href or href in seen_signin:
            continue
        # Match against login tokens in text, OR match URL path against
        # common auth keywords (catches icon-only buttons whose href
        # contains "/login" or "/signup" even with no visible text).
        _path_lower = urlparse(href).path.lower() if href.startswith("http") else href.lower()
        text_matches = any(tok in text for tok in LOGIN_TOKENS)
        url_matches  = any(
            tok in _path_lower
            for tok in ["login", "signin", "sign-in", "signup", "sign-up",
                        "register", "accounts/login", "auth/"]
        )
        if not text_matches and not url_matches:
            continue
        if href.startswith("/"):
            href = urljoin(origin, href)
        if not href.startswith("http"):
            continue
        if not is_trusted_domain(primary_domain, urlparse(href).netloc):
            continue
        seen_signin.add(href)
        signin_urls.append(href)

    # ── Fallback: try well-known auth paths if DOM discovery found nothing ──
    if not signin_urls:
        print("  [*] Priority scan: no login links in DOM — trying well-known auth paths ...")
        for auth_path in COMMON_AUTH_PATHS:
            candidate = f"{origin}{auth_path}"
            if candidate not in seen_signin:
                seen_signin.add(candidate)
                signin_urls.append(candidate)
        # We'll let _collect_policy_links_from_page handle 404s gracefully.

    if signin_urls:
        print(f"  [*] Priority scan: found {len(signin_urls)} sign-in page(s), scanning first ...")
        for url in signin_urls[:4]:
            await _collect_policy_links_from_page(url, "priority_signin")

    print("  [*] Priority scan: scanning homepage ...")
    await _collect_policy_links_from_page(base_url, "priority_homepage")

    # Follow management/settings pages — these are navigable pages that often
    # contain links to the actual policy documents. E.g. Instagram's
    # /privacy/cookie_settings/ page links to privacycenter.instagram.com/policies/cookies/
    mgmt_candidates = [
        l for l in found
        if any(tok in l["href"].lower() for tok in MANAGEMENT_URL_TOKENS)
    ]
    if mgmt_candidates:
        print(f"  [*] Priority scan: following {len(mgmt_candidates)} management page(s) for policy links ...")
        for mgmt in mgmt_candidates[:3]:
            await _collect_policy_links_from_page(mgmt["href"], "management_followup")

    return found


async def discover_from_sitemap(page, base_url: str, primary_domain: str) -> list:
    """
    Parse robots.txt and sitemap.xml to discover policy URLs.
    Handles sitemap index files (which reference sub-sitemaps) and
    regular sitemaps.  Returns list of {"href", "text", "source"} dicts.
    """
    import re as _re
    from xml.etree import ElementTree as ET

    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    found: list[dict] = []
    seen:  set[str]    = set()

    # Policy-related keywords to filter sitemap URLs
    SITEMAP_POLICY_TOKENS = [
        "privacy", "cookie", "cookies", "policy", "legal",
        "terms", "tos", "gdpr", "data-protection", "data_protection",
        "disclaimer", "compliance", "user-agreement",
    ]

    async def _fetch_text(url: str) -> str | None:
        """Navigate to a URL and return its text content, or None on failure."""
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            if resp and resp.status >= 400:
                return None
            return await page.content()
        except Exception:
            return None

    async def _parse_sitemap(sitemap_url: str, depth: int = 0) -> None:
        """Recursively parse a sitemap (or sitemap index) for policy URLs."""
        if depth > 2:
            return  # Prevent infinite recursion on deeply nested indices

        raw = await _fetch_text(sitemap_url)
        if not raw:
            return

        # Strip XML declaration and common HTML wrapper noise that Playwright
        # may inject (the raw content from page.content() is full HTML).
        # Extract the XML body from inside <body> or <pre> if present.
        body_match = _re.search(r'<(?:body|pre)[^>]*>(.*)</(?:body|pre)>', raw, _re.DOTALL)
        xml_text = body_match.group(1) if body_match else raw

        # Some servers return the raw XML without an HTML wrapper.
        # Attempt to find the root <urlset> or <sitemapindex> tag.
        xml_text = xml_text.strip()

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            # Try stripping anything before the first '<' (e.g. BOM, whitespace)
            first_tag = xml_text.find('<')
            if first_tag > 0:
                xml_text = xml_text[first_tag:]
            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError:
                print(f"  [!] sitemap: could not parse XML from {sitemap_url}")
                return

        # Handle XML namespace — sitemaps use xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        ns = ''
        ns_match = _re.match(r'\{([^}]+)\}', root.tag)
        if ns_match:
            ns = f'{{{ns_match.group(1)}}}'

        # Sitemap index → recurse into each sub-sitemap
        sub_sitemaps = root.findall(f'{ns}sitemap')
        if sub_sitemaps:
            print(f"  [*] sitemap: found sitemap index with {len(sub_sitemaps)} sub-sitemap(s)")
            for sm in sub_sitemaps:
                loc = sm.find(f'{ns}loc')
                if loc is not None and loc.text:
                    await _parse_sitemap(loc.text.strip(), depth + 1)
            return

        # Regular sitemap → extract <url><loc> entries
        url_entries = root.findall(f'{ns}url')
        for entry in url_entries:
            loc = entry.find(f'{ns}loc')
            if loc is None or not loc.text:
                continue
            href = loc.text.strip()
            href_lower = href.lower()

            # Only keep URLs that look policy-related
            if not any(tok in href_lower for tok in SITEMAP_POLICY_TOKENS):
                continue

            # Trust check
            link_domain = urlparse(href).netloc
            if not is_trusted_domain(primary_domain, link_domain):
                continue

            if href not in seen:
                seen.add(href)
                found.append({"href": href, "text": "", "source": "sitemap"})
                print(f"  [sitemap] {href[:80]}")

    # ── Step 1: Discover sitemap URLs from robots.txt ─────────────────────
    sitemap_urls: list[str] = []
    robots_text = await _fetch_text(f"{origin}/robots.txt")
    if robots_text:
        # Extract text from HTML wrapper if Playwright wrapped it
        body_match = _re.search(r'<(?:body|pre)[^>]*>(.*)</(?:body|pre)>', robots_text, _re.DOTALL)
        plain = body_match.group(1) if body_match else robots_text
        for line in plain.splitlines():
            line = line.strip()
            if line.lower().startswith("sitemap:"):
                sm_url = line.split(":", 1)[1].strip()
                # Re-attach the scheme if the split above ate it
                if not sm_url.startswith("http"):
                    # "Sitemap: https://example.com/..." → split on first ":" gives
                    # " https://..." — but some have "Sitemap:https://..."
                    sm_url = line[len("sitemap:"):].strip()
                if sm_url.startswith("http"):
                    sitemap_urls.append(sm_url)

    # ── Step 2: Fall back to well-known sitemap locations ─────────────────
    if not sitemap_urls:
        sitemap_urls = [
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap-index.xml",
            f"{origin}/sitemaps.xml",
        ]

    print(f"  [*] sitemap: checking {len(sitemap_urls)} sitemap URL(s) ...")
    for sm in sitemap_urls:
        await _parse_sitemap(sm)

    return found


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
                         _depth: int = 0,
                         _from_priority: bool = False) -> dict | None:
    """
    Navigate to a policy URL, extract clean text, save as Markdown.
    Handles JS-rendered / SPA pages by scrolling and waiting for content.
    Returns a metadata dict or None on failure.
    """
    # Auth-related URL tokens — pages with these in their path are login/
    # signup/password-reset pages, NOT policy documents.  Used to detect
    # auth-gate redirects and prevent saving login page content as a policy.
    AUTH_URL_TOKENS = [
        "/login", "/signin", "/sign-in", "/signup", "/sign-up",
        "/register", "/accounts/login", "/accounts/signup",
        "/auth/", "/sso/", "/oauth/", "/password/reset",
        "/password-reset", "/forgot-password", "/account/recover",
    ]

    def _is_auth_url(check_url: str) -> bool:
        """True if url looks like a login, signup, or password-reset page."""
        path = urlparse(check_url).path.lower()
        return any(tok in path for tok in AUTH_URL_TOKENS)

    print(f"\n  [→] Fetching [{category}]: {url}")
    try:
        # Use domcontentloaded instead of networkidle — networkidle never
        # fires on sites with persistent WebSockets, analytics pings, or
        # long-polling (e.g. Overleaf, many SPAs).  The adaptive content
        # polling loop further down handles waiting for dynamic content.
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Fail fast on obvious HTTP errors (e.g., Overleaf's fake privacy policy 404)
        if resp and not resp.ok:
            print(f"  [✗] HTTP Error {resp.status} for {url} — skipping")
            return None

        # Brief stabilisation wait for JS frameworks to hydrate
        try:
            await page.wait_for_load_state("load", timeout=8000)
        except Exception:
            pass  # load event may never fire on some SPAs — that is fine

        # ── Auth-redirect detection ────────────────────────────────────────
        # If the site redirected us to a login/signup/password-reset page,
        # the policy URL is auth-gated and we cannot scrape it.
        final_url = page.url
        if _is_auth_url(final_url) and not _is_auth_url(url):
            print(f"  [!] Auth-gate redirect detected: {url} → {final_url} — skipping")
            return None

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
        # Adaptive wait: poll until page content stops growing (lazy-load complete)
        # instead of a fixed 5-second sleep.  Fast sites finish in 1-2s.
        _prev_len = 0
        for _ in range(10):
            _curr_len = await page.evaluate(
                "() => (document.body.innerText || '').length"
            )
            if _curr_len == _prev_len and _curr_len > 0:
                break  # Content has stabilised
            _prev_len = _curr_len
            await asyncio.sleep(1)
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

        # Initialise raw_text — will be populated after accordion expansion below.
        raw_text = None

        # Wait for React/SPA content to render before expanding accordions.
        try:
            for _ in range(8):
                content_len = await page.evaluate("""
                    () => {
                        const main = document.querySelector('main')
                            || document.querySelector('article')
                            || document.querySelector('[role="main"]')
                            || document.body;
                        return main ? (main.innerText || '').trim().length : 0;
                    }
                """)
                if content_len > 500:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass

        # Expand all accordion / disclosure sections (3 passes, waits between each).
        try:
            for _pass in range(3):
                expanded = await page.evaluate("""
                    () => {
                        const isVisible = (el) => {
                            const rect = el.getBoundingClientRect();
                            if (!rect.width || !rect.height) return false;
                            const style = window.getComputedStyle(el);
                            return style.visibility !== 'hidden' && style.display !== 'none';
                        };
                        let clicked = 0;
                        document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                            if (!isVisible(el)) return;
                            try { el.click(); clicked++; } catch (e) {}
                        });
                        const EXPAND_TOKENS = [
                            'see more', 'see details', 'learn more', 'view more',
                            'show more', 'more information', 'read more', 'expand', 'details'
                        ];
                        document.querySelectorAll('button, [role="button"]').forEach(el => {
                            const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
                            if (!txt || !isVisible(el)) return;
                            if (EXPAND_TOKENS.some(t => txt.includes(t))) {
                                try { el.click(); clicked++; } catch (e) {}
                            }
                        });
                        return clicked;
                    }
                """)
                if expanded == 0:
                    break
                await asyncio.sleep(1.5)
        except Exception:
            pass

        # Re-extract innerText after accordion expansion
        try:
            expanded_text = await page.evaluate("""
                () => {
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
            if expanded_text and len(expanded_text.strip()) > 300:
                raw_text = expanded_text
        except Exception:
            pass

        # Hash-targeted HTML extraction: if URL has an anchor (e.g. #Cookies),
        # extract just that section's outerHTML using the browser's DOM tree.
        hash_frag = urlparse(url).fragment
        raw_html = ""
        
        if hash_frag:
            isolated_html = await page.evaluate(f"""
                () => {{
                    const target = document.getElementById('{hash_frag}') || document.querySelector('[name="{hash_frag}"]');
                    if (!target) return null;
                    
                    // If the target itself is a substantial container (like Overleaf's tab-panes),
                    // no need to traverse siblings. It already wraps everything!
                    if (target.innerText && target.innerText.length > 500) {{
                        return target.outerHTML;
                    }}
                    
                    // If it's a short anchor inside a heading, treat the parent heading as the target
                    const tagPattern = /^H[1-6]$/i;
                    let activeTarget = target;
                    if (!tagPattern.test(target.tagName) && target.parentElement && tagPattern.test(target.parentElement.tagName)) {{
                        activeTarget = target.parentElement;
                    }}
                    
                    const startLevel = tagPattern.test(activeTarget.tagName) ? parseInt(activeTarget.tagName[1]) : 6;
                    
                    const wrapper = document.createElement('div');
                    wrapper.appendChild(activeTarget.cloneNode(true));
                    
                    let current = activeTarget.nextElementSibling;
                    while (current) {{
                        if (tagPattern.test(current.tagName)) {{
                            const lvl = parseInt(current.tagName[1]);
                            if (lvl <= startLevel) break;
                        }}
                        wrapper.appendChild(current.cloneNode(true));
                        current = current.nextElementSibling;
                    }}
                    
                    return wrapper.innerText.length > 100 ? wrapper.outerHTML : null;
                }}
            """)
            if isolated_html:
                print(f"  [+] Isolated section #{hash_frag} ({len(isolated_html)} bytes of HTML)")
                raw_html = isolated_html
                
        # If no hash or isolation failed, grab the whole page body
        if not raw_html:
            raw_html = await page.content()
            
        soup  = BeautifulSoup(raw_html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else category.replace("_", " ").title()

        # Convert HTML to structured markdown
        markdown_content = html_to_markdown(soup, base_url=url)

        # If markdown is too short (JS-heavy SPA), fall back to plain innerText
        if len(markdown_content.strip()) < 1000 and raw_text and len(raw_text.strip()) > 1000:
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
        if word_count < 500 and _depth < 2 and not _from_priority:
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
                            await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                            try:
                                await page.wait_for_load_state("load", timeout=5000)
                            except Exception:
                                pass
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
        if word_count < THIN_THRESHOLD and _depth < 3 and not _from_priority:
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
                    # Reject deep links that point to auth/login pages
                    if _is_auth_url(href):
                        continue
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

        # ── Step 2a: Priority scan — sign-in page first, then homepage ─────────
        print("[*] Running priority scan (sign-in page → homepage) ...")
        priority_links = await extract_priority_policy_links(page, target_url, domain)
        if priority_links:
            existing_hrefs = {l["href"] for l in telemetry_links}
            inserted = 0
            for link in priority_links:
                if link["href"] not in existing_hrefs:
                    telemetry_links.insert(0, link)
                    existing_hrefs.add(link["href"])
                    inserted += 1
            print(f"[*] Priority scan: {inserted} new link(s) prepended to candidate pool.")
        else:
            print("[*] Priority scan: no links found — relying on telemetry + crawl.")

        # ── Step 2b: Crawl as fallback / augmentation ─────────────────────────
        if not telemetry_links:
            print("[*] No links yet — crawling site for policy links ...")
            telemetry_links = await discover_policy_links_from_crawl(page, target_url, domain)
            print(f"[*] Found {len(telemetry_links)} policy link(s) via crawl.")
        else:
            print("[*] Augmenting with full site crawl ...")
            crawl_links = await discover_policy_links_from_crawl(page, target_url, domain)
            existing_hrefs = {l["href"] for l in telemetry_links}
            for link in crawl_links:
                if link["href"] not in existing_hrefs:
                    telemetry_links.append(link)
                    existing_hrefs.add(link["href"])
            print(f"[*] Total unique policy links: {len(telemetry_links)}")

        # ── Step 2c: Sitemap discovery (robots.txt + sitemap.xml) ──────────
        print("[*] Checking robots.txt / sitemap.xml for policy URLs ...")
        sitemap_links = await discover_from_sitemap(page, target_url, domain)
        if sitemap_links:
            existing_hrefs = {l["href"] for l in telemetry_links}
            added = 0
            for link in sitemap_links:
                if link["href"] not in existing_hrefs:
                    telemetry_links.append(link)
                    existing_hrefs.add(link["href"])
                    added += 1
            if added:
                print(f"[*] Sitemap discovery: {added} new policy link(s) added.")
            else:
                print("[*] Sitemap discovery: no new links (all already known).")
        else:
            print("[*] Sitemap discovery: no policy links found in sitemaps.")

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

        # Ecosystem-specific WELLKNOWN URLs — major platforms host policies on
        # separate domains (e.g., Meta hosts cookies policy on privacycenter.
        # instagram.com).  Keyed by root domain → {category → [full urls]}.
        ECOSYSTEM_WELLKNOWN_URLS = {
            "instagram.com": {
                "cookie_policy": [
                    "https://privacycenter.instagram.com/policies/cookies/",
                    "https://www.facebook.com/policies/cookies/",
                ],
                "privacy_policy": [
                    "https://privacycenter.instagram.com/policy",
                ],
            },
            "facebook.com": {
                "cookie_policy": [
                    "https://www.facebook.com/policies/cookies/",
                    "https://www.facebook.com/help/cookies",
                ],
                "privacy_policy": [
                    "https://www.facebook.com/privacy/policy/",
                    "https://www.facebook.com/privacy/center/",
                ],
            },
            "whatsapp.com": {
                "cookie_policy": [
                    "https://www.whatsapp.com/legal/cookies",
                ],
            },
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
            # +200 boost for links discovered directly inside a consent/cookie popup
            # These are the most authoritative source — e.g. Instagram only shows
            # its cookie policy link inside the GDPR consent dialog
            if link.get("source") == "consent_popup":
                url_score += 200
            # +100 boost when URL path or fragment contains the exact category keyword
            _parsed = urlparse(href)
            _path_frag_lower = (_parsed.path + "#" + _parsed.fragment).lower()
            if category == "cookie_policy" and ("cookie" in _path_frag_lower):
                url_score += 100
            if category == "privacy_policy" and ("privacy" in _path_frag_lower):
                url_score += 100
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
            source = link.get("source", "telemetry_or_crawl")
            candidates[category].append({"href": href, "text": text, "score": url_score, "source": source})

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

        # Add ecosystem-specific full URLs (e.g., privacycenter.instagram.com
        # for Meta properties) — these are highly authoritative.
        domain_root = get_root_domain(domain)
        eco_urls = ECOSYSTEM_WELLKNOWN_URLS.get(domain_root, {})
        for eco_category, eco_full_urls in eco_urls.items():
            if eco_category not in candidates:
                candidates[eco_category] = []
            for eco_url in eco_full_urls:
                # +150 because ecosystem URLs are the real policy pages
                candidates[eco_category].append({
                    "href": eco_url,
                    "text": "",
                    "score": score_url(eco_url) + 150,
                    "source": "ecosystem_wellknown",
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

        # Only collect privacy and cookie policy documents
        categorised = {
            cat: link for cat, link in categorised.items()
            if cat in ("privacy_policy", "cookie_policy")
        }
        print(f"\n[*] Scraping {len(categorised)} policy document(s) (privacy + cookie only) ...\n")

        # ── Step 4: Scrape each policy page ───────────────────────────────────
        # Each scrape uses a fresh page to avoid cookie / local-storage bleed
        # between navigations (e.g. a consent dialog dismissed on homepage
        # would not reappear on the policy page with a shared page object).
        results: list[dict] = []
        scraped_by_category: Dict[str, str] = {}
        for category, link in categorised.items():
            is_priority = link.get("source", "").startswith("priority")
            scrape_page = await context.new_page()
            try:
                result = await scrape_policy(
                    scrape_page, link["href"], category, domain, output_path,
                    _from_priority=is_priority,
                )
            finally:
                await scrape_page.close()
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