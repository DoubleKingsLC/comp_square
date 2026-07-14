# Next Steps

> Progress log with dates: see `PROGRESS.md`. Paper-to-code mapping: see `Implementation_Pointers.md`.

- Fix the scraping for complex sites like facebook
- Login/Signup Page should be Priority 1/ Otherwise fallback to normal ranking
- Fragmented URLS should be saved in seperate files.
- Privacy Policy/Cookie Policy is the main focus. 
- Comment out the others for now
- Decide on input for RAG pipeline
- ~~HAR behavioral evidence extractor~~ ✅ done 2026-07-12 (`ingestion/har_extractor.py`)
- Run extractor on real HARs locally (`--update-lists` first) and review output
- Build `rag/scorer.py` (IRAC prompt, NOT_ADDRESSED verdict, discrepancy types)
- Consent-banner interaction in telemetry collector (accept/reject protocol)
- **Backlog:** post-login observation — compare data actually collected while logged in vs. what was consented to (details in PROGRESS.md backlog)
