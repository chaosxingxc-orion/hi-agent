# Downstream Response Notices

Manifest: historical-index

This directory contains delivery notices formatted for the research-intelligence team (one specific downstream consumer of hi-agent).

**These are NOT the canonical platform delivery format.** They are examples of how one consumer has chosen to format their response notices.

To validate a downstream response notice for the research-intelligence team format:
```bash
python scripts/check_downstream_response_format.py <notice-file>
```

The platform's core CI (`scripts/check_doc_consistency.py`) does NOT enforce this format.
