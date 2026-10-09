"""Quality loop: learn from real calls without fine-tuning (docs/QUALITY_LOOP.md).

* ``store``     - consent-gated, redacted, encrypted transcripts + retention + erasure
* ``labels``    - the fixed label set, ratings and the WhatsApp rating line (not wired)
* ``evalrun``   - scripted caller scenarios through the front door, deterministic scoring
* ``cli``       - ``friday review`` and ``friday eval``
* ``hook``      - the one subscriber that connects the store to ``FrontDoorCallFinished``

Owner: quality loop. Nothing here changes how a call is handled.
"""
