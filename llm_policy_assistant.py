"""
LLM Policy Assistant
--------------------

This module centralises all LLM-related logic used by `policy_scraper.py`.
It is intentionally lightweight and targets a local Ollama instance.

Ollama configuration (environment variables):
  - OLLAMA_BASE_URL  : base URL (default: http://localhost:11434)
  - OLLAMA_MODEL     : chat model name (default: llama3.1:8b)

The two main entry points are:
  - select_policy_urls_via_llm(...)
  - validate_policies_via_llm(...)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


@dataclass
class PolicyCandidate:
    category: str
    url: str
    text: str
    source: str  # e.g. "telemetry", "crawl", "wellknown"
    score: int


def _llm_available() -> bool:
    """
    For a local Ollama instance we simply assume availability unless the
    user explicitly disables it via DISABLE_LLM.
    """
    return os.getenv("DISABLE_LLM", "0") != "1"


def _llm_chat(system_prompt: str, user_prompt: str) -> str:
    """
    Minimal Ollama chat client using the native /api/chat endpoint.
    Returns the assistant message content as plain text.
    """
    if not _llm_available():
        raise RuntimeError("LLM calls disabled via DISABLE_LLM.")

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise RuntimeError(f"Failed to reach Ollama at {url}: {e}") from e

    parsed = json.loads(body)
    # Ollama's /api/chat returns: {"message": {"role": "...", "content": "..."}, ...}
    msg = parsed.get("message") or {}
    return msg.get("content", "")


def select_policy_urls_via_llm(
    domain: str,
    telemetry_summary: Dict[str, Any],
    har_path: Optional[str],
    candidates: List[PolicyCandidate],
) -> Dict[str, Dict[str, Any]]:
    """
    Ask the LLM to select the best URL for each of:
      - privacy_policy
      - cookie_policy

    Returns a dict:
        {
          "privacy_policy": {
              "url": "...",
              "reason": "...",
          },
          "cookie_policy": {
              "url": "...",
              "reason": "...",
          }
        }

    On failure, returns an empty dict and the caller should fall back to
    heuristic scoring.
    """
    if not _llm_available():
        return {}

    # Compact telemetry to avoid huge payloads.
    compact_telemetry = {
        "meta": telemetry_summary.get("meta", {}),
        "declared_vs_observed": {
            "policy_links": telemetry_summary.get("declared_vs_observed", {}).get("policy_links", []),
            "meta_tags": telemetry_summary.get("declared_vs_observed", {}).get("meta_tags", []),
        },
        "observed_behavior": {
            "network_summary": telemetry_summary.get("observed_behavior", {}).get("network_summary", {}),
            "cookies": {
                "total": telemetry_summary.get("observed_behavior", {})
                .get("cookies", {})
                .get("total"),
                "third_party_count": telemetry_summary.get("observed_behavior", {})
                .get("cookies", {})
                .get("third_party_count"),
            },
        },
    }

    candidate_payload = [
        {
            "category": c.category,
            "url": c.url,
            "anchor_text": c.text,
            "source": c.source,
            "local_score": c.score,
        }
        for c in candidates
    ]

    system_prompt = (
        "You are a privacy compliance assistant. "
        "You are given a website domain, structured telemetry (network and policy links), "
        "and a list of candidate URLs for privacy and cookie policies. "
        "Use both the on-page data and your broader knowledge / OSINT of large websites "
        "to pick the most authoritative PRIVACY POLICY and COOKIE POLICY URLs for this domain. "
        "If multiple URLs redirect to a canonical path, prefer the canonical / legal page. "
        "Return STRICT JSON only, no commentary."
    )

    user_prompt = json.dumps(
        {
            "domain": domain,
            "har_path": har_path,
            "telemetry": compact_telemetry,
            "candidates": candidate_payload,
            "instructions": (
                "For each of the categories 'privacy_policy' and 'cookie_policy', "
                "choose at most one URL from candidates whose category matches. "
                "If you are not confident for a category, set its url to null."
            ),
        },
        indent=2,
    )

    try:
        raw = _llm_chat(system_prompt, user_prompt)
        # Some models may wrap JSON in markdown fences; strip crudely.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            raw = raw.lstrip("json").strip()
        parsed = json.loads(raw)
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for key in ("privacy_policy", "cookie_policy"):
        entry = parsed.get(key)
        if isinstance(entry, dict) and entry.get("url"):
            result[key] = {"url": entry["url"], "reason": entry.get("reason", "")}

    return result


def validate_policies_via_llm(
    domain: str,
    telemetry_summary: Dict[str, Any],
    selected_urls: Dict[str, str],
    scraped_markdown_by_category: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """
    Ask the LLM to sanity-check whether the scraped privacy/cookie policies
    look correct for the given domain.

    Returns a dict like:
        {
          "privacy_policy": {"looks_correct": true, "reason": "..."},
          "cookie_policy":  {"looks_correct": true, "reason": "..."}
        }
    """
    if not _llm_available():
        return {}

    compact_telemetry = {
        "meta": telemetry_summary.get("meta", {}),
        "declared_vs_observed": {
            "policy_links": telemetry_summary.get("declared_vs_observed", {}).get("policy_links", []),
        },
    }

    # Truncate very long markdown to keep payload manageable.
    truncated_docs: Dict[str, str] = {}
    for cat, content in scraped_markdown_by_category.items():
        if not isinstance(content, str):
            continue
        if len(content) > 40_000:
            truncated_docs[cat] = content[:40_000]
        else:
            truncated_docs[cat] = content

    system_prompt = (
        "You are a meticulous privacy policy auditor. "
        "Given a website domain, telemetry summary, and scraped policy markdown, "
        "decide whether each document is plausibly the correct PRIVACY POLICY or "
        "COOKIE POLICY for that specific domain (not some other product or company). "
        "Be especially wary of: whitepaper-like pages, marketing pages, or policies "
        "belonging to a parent/child company where this domain is only mentioned in passing. "
        "Return STRICT JSON only."
    )

    user_payload = {
        "domain": domain,
        "telemetry": compact_telemetry,
        "selected_urls": selected_urls,
        "scraped_markdown": truncated_docs,
        "instructions": (
            "For each of 'privacy_policy' and 'cookie_policy', output an object with "
            "keys: looks_correct (boolean) and reason (short string)."
        ),
    }

    try:
        raw = _llm_chat(system_prompt, json.dumps(user_payload, indent=2))
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            raw = raw.lstrip("json").strip()
        parsed = json.loads(raw)
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for key in ("privacy_policy", "cookie_policy"):
        entry = parsed.get(key)
        if isinstance(entry, dict) and "looks_correct" in entry:
            result[key] = {
                "looks_correct": bool(entry.get("looks_correct")),
                "reason": entry.get("reason", ""),
            }

    return result