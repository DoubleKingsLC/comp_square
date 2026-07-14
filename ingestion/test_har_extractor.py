"""
Self-contained test for ingestion/har_extractor.py — no network, no real HAR needed.
Run:  python3 ingestion/test_har_extractor.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from har_extractor import extract, to_prompt_context  # noqa: E402


def _entry(url, set_cookies=None, t="2026-07-12T10:00:00.000Z"):
    headers = [{"name": "Content-Type", "value": "text/html"}]
    for sc in (set_cookies or []):
        headers.append({"name": "set-cookie", "value": sc})
    return {"startedDateTime": t,
            "request": {"url": url, "method": "GET", "headers": []},
            "response": {"status": 200, "headers": headers}}


def make_fixtures(d: Path):
    har = {"log": {"version": "1.2", "entries": [
        _entry("https://www.example.com/", ["sessionid=abc; Path=/; HttpOnly"]),
        _entry("https://googleads.g.doubleclick.net/pagead/id",
               ["id=XYZ123; Domain=.doubleclick.net; Expires=Wed, 12 Jul 2028 10:00:00 GMT; Path=/"]),
        _entry("https://pixel.rubiconproject.com/tap.php",
               ["rpx=999; Domain=.rubiconproject.com; Max-Age=31536000; Path=/"]),
        _entry("https://cdn.example.com/app.js"),
        # third-party but NOT tracker-listed -> must NOT be profiling
        _entry("https://api.stripe.com/v1/ping", ["m=1; Domain=.stripe.com; Max-Age=63072000"]),
        # tracker-listed but short-lived (1h) -> must NOT be profiling
        _entry("https://www.facebook.com/tr?id=1", ["fr=short; Domain=.facebook.com; Max-Age=3600"]),
        _entry("https://ib.adnxs.com/getuid",
               ["anj=Kfw; Domain=.adnxs.com; Expires=Sat, 12 Jul 2027 10:00:00 GMT"]),
    ]}}
    (d / "example.har").write_text(json.dumps(har))

    tele = {
        "meta": {"url": "https://www.example.com", "final_url": "https://www.example.com/",
                 "domain": "www.example.com", "etld1": "example.com",
                 "captured_at": "2026-07-12T10:00:05+00:00"},
        "observed_behavior": {
            "cookies": {"all_cookies": [
                {"name": "sessionid", "domain": "www.example.com", "expires": -1, "third_party": False},
                # JS-set profiling cookie missed by Set-Cookie headers
                {"name": "_ga", "domain": ".google-analytics.com", "expires": 1815000000, "third_party": True},
                # duplicate of HAR cookie -> must be deduped
                {"name": "id", "domain": ".doubleclick.net", "expires": 1846200000, "third_party": True},
            ]},
            "fingerprinting_traps": {"alarms_triggered": 1, "alarms": [
                "COMPLIANCE_ALARM: HTMLCanvasElement.toDataURL (canvas fingerprinting) accessed at 2026-07-12T10:00:03Z"]},
        },
        "visual_evidence": {"interactable_elements": {"consent_related_count": 2}},
    }
    (d / "example_telemetry.json").write_text(json.dumps(tele))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_fixtures(d)

        ev = extract(d / "example.har", telemetry=d / "example_telemetry.json",
                     declared_domains=["doubleclick.net", "facebook.com"],
                     declared_cookies=["id", "fr", "sessionid"])

        # Trevisan rule: id (731d), rpx (365d), anj (365d) from HAR + _ga from JS context
        assert ev["summary"]["pre_consent_profiling_cookies"] == 4, ev["summary"]
        prof_names = {c["name"] for c in ev["pre_consent_profiling_cookies"]}
        assert prof_names == {"id", "rpx", "anj"}, prof_names
        # exclusions
        assert "m" not in prof_names        # not tracker-listed
        assert "fr" not in prof_names       # short-lived
        assert "sessionid" not in prof_names  # first-party session
        # JS-set dedup
        js = [(c["name"]) for c in ev["js_set_profiling_cookies"]]
        assert js == ["_ga"], js
        # Lalaine typology
        dva = ev["declared_vs_actual"]
        assert dva["discrepancy_type"] == "neglect"
        assert set(dva["undeclared_domains"]) == {"adnxs.com", "rubiconproject.com", "stripe.com"}
        # fingerprinting + consent UI passthrough
        assert ev["summary"]["fingerprinting_alarms"] == 1
        assert ev["consent_ui_detected"] is True

        # HAR-only path
        ev2 = extract(d / "example.har")
        assert ev2["domain"] == "example.com"
        assert ev2["summary"]["pre_consent_profiling_cookies"] == 3

        # prompt rendering doesn't crash and contains key content
        ctx = to_prompt_context(ev)
        assert "doubleclick.net" in ctx and "POTENTIAL" in ctx

    print("[✓] all har_extractor tests passed")


if __name__ == "__main__":
    main()
