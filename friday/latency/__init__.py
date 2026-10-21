"""Latency work for live calls (docs/LATENCY.md, 2026-10-21). Three switches, all default OFF, none
changes a spoken word: ``speculative`` (understand early), ``streaming`` (speak the model's reply
sentence by sentence), the intent classifier lives in ``friday/playbooks/classifier.py``.
``simulator`` measures the reply gap before / after with a virtual clock."""
